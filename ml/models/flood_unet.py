"""
OrbitalMind — Flood Attention U-Net Model
==========================================
Wraps ``segmentation-models-pytorch`` to provide:
- An Attention U-Net with EfficientNet-B0 encoder (2-channel SAR input)
- FP16 mixed-precision inference (RTX 3050 / 4 GB VRAM safe)
- Batched patch inference with sigmoid confidence output
- Model save / load utilities

Architecture
------------
    Input:  (B, 2, 256, 256)  — VV + VH SAR bands, normalised
    Encoder: EfficientNet-B0 (ImageNet pre-trained, channels adapted to 2)
    Decoder: U-Net with scSE attention gates on skip connections
    Output: (B, 1, 256, 256)  — float32 logit → sigmoid → flood probability

VRAM budget at batch size 8, FP16:
    ~1.4 GB encoder activations + ~0.6 GB decoder = ~2.0 GB peak
    Safe headroom on 4 GB VRAM card.

Usage
-----
    from ml.models.flood_unet import build_flood_unet, process_patches
    import torch

    model = build_flood_unet().cuda().half()
    patches = torch.randn(12, 2, 256, 256)   # 12 tiles
    masks, confs = process_patches(model, patches, batch_size=8)
"""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Optional

import numpy as np
import torch
import torch.nn as nn

# ---------------------------------------------------------------------------
# Guard: check segmentation-models-pytorch is installed
# ---------------------------------------------------------------------------
try:
    import segmentation_models_pytorch as smp  # type: ignore[import]
except ImportError as exc:
    raise ImportError(
        "segmentation-models-pytorch is not installed.\n"
        "Run: pip install segmentation-models-pytorch"
    ) from exc


# ---------------------------------------------------------------------------
# Model factory
# ---------------------------------------------------------------------------

def build_flood_unet(
    encoder_name: str = "efficientnet-b0",
    encoder_weights: Optional[str] = "imagenet",
    in_channels: int = 2,
    classes: int = 1,
    attention_type: str = "scse",
) -> nn.Module:
    """Build and return the Flood Attention U-Net.

    Uses ``segmentation_models_pytorch.Unet`` with scSE (Squeeze-and-Channel
    Squeeze-and-Excitation) attention gates on decoder blocks — the standard
    Attention U-Net approximation in SMP.

    Parameters
    ----------
    encoder_name : str
        Timm / SMP encoder identifier. Default ``"efficientnet-b0"``
        (EfficientNet-B0, ~4M params — fits comfortably in 4 GB VRAM).
    encoder_weights : str or None
        Pre-trained weight source.  ``"imagenet"`` downloads ImageNet weights
        on first call.  Set to ``None`` to train from scratch.
    in_channels : int
        Number of input channels.  ``2`` = VV + VH SAR bands.
    classes : int
        Number of output mask classes.  ``1`` = binary flood / no-flood.
    attention_type : str
        Decoder attention mechanism.  ``"scse"`` (default) adds concurrent
        channel and spatial squeeze-and-excitation to each decoder block.
        Set to ``None`` for a vanilla U-Net.

    Returns
    -------
    torch.nn.Module
        Initialised U-Net model in training mode (``model.eval()`` for
        inference).  Weights are NOT moved to GPU — call ``.cuda()`` or
        ``.to(device)`` after.

    Examples
    --------
    >>> model = build_flood_unet()
    >>> model.eval()
    >>> x = torch.randn(1, 2, 256, 256)
    >>> with torch.no_grad():
    ...     out = model(x)
    >>> out.shape
    torch.Size([1, 1, 256, 256])
    """
    model = smp.Unet(
        encoder_name=encoder_name,
        encoder_weights=encoder_weights,
        in_channels=in_channels,
        classes=classes,
        decoder_attention_type=attention_type,
        activation=None,  # raw logits; we apply sigmoid explicitly
    )
    return model


# ---------------------------------------------------------------------------
# Single-patch FP16 inference
# ---------------------------------------------------------------------------

def run_inference(
    model: nn.Module,
    patch_tensor: torch.Tensor,
    device: Optional[torch.device] = None,
) -> tuple[np.ndarray, float]:
    """Run FP16 inference on a single patch tensor.

    Parameters
    ----------
    model : nn.Module
        Flood U-Net in eval mode, already moved to ``device``.
    patch_tensor : torch.Tensor
        Shape ``(C, H, W)`` or ``(1, C, H, W)``.  Values should be
        pre-normalised (zero-mean, unit-std per band).
    device : torch.device, optional
        Target device.  Auto-detected (CUDA → CPU) if ``None``.

    Returns
    -------
    mask : np.ndarray
        Binary flood mask, shape ``(H, W)``, dtype ``uint8`` (0 or 1).
    confidence : float
        Mean sigmoid probability over the predicted flood pixels
        (NaN if no flood pixels predicted).

    Notes
    -----
    Uses ``torch.cuda.amp.autocast`` for FP16 on CUDA.  Falls back to
    full precision on CPU (autocast is a no-op).
    """
    if device is None:
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    if patch_tensor.dim() == 3:
        patch_tensor = patch_tensor.unsqueeze(0)  # (1, C, H, W)

    patch_tensor = patch_tensor.to(device, dtype=torch.float32)

    model.eval()
    with torch.no_grad():
        with torch.cuda.amp.autocast(enabled=device.type == "cuda"):
            logits = model(patch_tensor)          # (1, 1, H, W)

    prob = torch.sigmoid(logits).squeeze().cpu().float().numpy()  # (H, W)
    mask = (prob > 0.5).astype(np.uint8)

    flood_probs = prob[mask == 1]
    confidence  = float(flood_probs.mean()) if len(flood_probs) > 0 else float("nan")

    return mask, confidence


# ---------------------------------------------------------------------------
# Batched patch inference
# ---------------------------------------------------------------------------

def process_patches(
    model: nn.Module,
    patches: list[np.ndarray] | torch.Tensor,
    batch_size: int = 8,
    device: Optional[torch.device] = None,
) -> tuple[list[np.ndarray], list[float]]:
    """Run batched FP16 inference over a list of SAR patches.

    Splits patches into batches of ``batch_size`` to control VRAM usage.
    Each batch is processed with ``torch.cuda.amp.autocast`` (FP16 on CUDA).

    Parameters
    ----------
    model : nn.Module
        Flood U-Net in eval mode, moved to ``device``.
    patches : list of np.ndarray or torch.Tensor
        Each element shape ``(C, H, W)`` where C=2 (VV, VH), H=W=256.
        Numpy arrays are converted to float32 tensors automatically.
    batch_size : int
        Number of patches per forward pass.  Default 8 (safe for 4 GB VRAM
        with FP16 and 256×256 patches).
    device : torch.device, optional
        Target device.  Auto-detected if ``None``.

    Returns
    -------
    masks : list[np.ndarray]
        Binary flood masks, one per input patch, shape ``(H, W)``, uint8.
    confidences : list[float]
        Mean flood probability per patch (NaN if no flood pixels).

    Examples
    --------
    >>> model = build_flood_unet().eval()
    >>> patches = [np.random.randn(2, 256, 256).astype(np.float32)] * 20
    >>> masks, confs = process_patches(model, patches, batch_size=8)
    >>> len(masks)
    20
    """
    if device is None:
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    model = model.to(device)
    model.eval()

    # Normalise inputs to tensors
    tensor_list: list[torch.Tensor] = []
    for p in patches:
        if isinstance(p, np.ndarray):
            p = torch.from_numpy(p.astype(np.float32))
        tensor_list.append(p)

    masks:       list[np.ndarray] = []
    confidences: list[float]      = []

    n_total  = len(tensor_list)
    n_batches = (n_total + batch_size - 1) // batch_size

    for batch_idx in range(n_batches):
        start = batch_idx * batch_size
        end   = min(start + batch_size, n_total)

        batch = torch.stack(tensor_list[start:end]).to(device, dtype=torch.float32)

        with torch.no_grad():
            with torch.cuda.amp.autocast(enabled=device.type == "cuda"):
                logits = model(batch)              # (B, 1, H, W)

        probs = torch.sigmoid(logits).squeeze(1).cpu().float().numpy()  # (B, H, W)

        for prob in probs:
            mask        = (prob > 0.5).astype(np.uint8)
            flood_probs = prob[mask == 1]
            conf        = float(flood_probs.mean()) if len(flood_probs) > 0 else float("nan")
            masks.append(mask)
            confidences.append(conf)

        processed = end
        print(
            f"\r[MODEL] Processed {processed}/{n_total} patches "
            f"({100*processed/n_total:.0f}%) …",
            end="",
            flush=True,
        )

    print()  # newline after progress
    return masks, confidences


# ---------------------------------------------------------------------------
# Save / load utilities
# ---------------------------------------------------------------------------

def save_model(model: nn.Module, path: Path | str, metadata: dict = None) -> None:
    """Save model ``state_dict`` plus optional metadata to a .pt checkpoint.

    Parameters
    ----------
    model : nn.Module
        Model to save (state_dict only — architecture must be reconstructed
        via ``build_flood_unet()`` before loading).
    path : Path or str
        Destination path (e.g. ``"checkpoints/flood_unet_v1.pt"``).
    metadata : dict, optional
        Extra data to store alongside weights (e.g. training epoch, val IoU).

    Examples
    --------
    >>> save_model(model, "checkpoints/best.pt", {"epoch": 30, "val_iou": 0.87})
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    checkpoint = {"state_dict": model.state_dict()}
    if metadata:
        checkpoint["metadata"] = metadata

    torch.save(checkpoint, path)
    print(f"[MODEL] Saved checkpoint → {path}")


def load_model(
    path: Path | str,
    device: Optional[torch.device] = None,
    **build_kwargs,
) -> nn.Module:
    """Load a saved flood U-Net checkpoint.

    Reconstructs the model with ``build_flood_unet(**build_kwargs)``, then
    loads the saved ``state_dict``.

    Parameters
    ----------
    path : Path or str
        Path to the ``.pt`` checkpoint file.
    device : torch.device, optional
        Target device. Auto-detected if ``None``.
    **build_kwargs
        Keyword arguments forwarded to ``build_flood_unet()`` — use these
        to override ``encoder_name``, ``in_channels``, etc. if needed.

    Returns
    -------
    nn.Module
        Model in eval mode with loaded weights.

    Raises
    ------
    FileNotFoundError
        If the checkpoint file does not exist.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Checkpoint not found: {path}")

    if device is None:
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    # Suppress SMP ImageNet weight download warning (weights come from checkpoint)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        build_kwargs.setdefault("encoder_weights", None)   # skip imagenet download
        model = build_flood_unet(**build_kwargs)

    checkpoint = torch.load(path, map_location=device)
    model.load_state_dict(checkpoint["state_dict"])
    model = model.to(device).eval()

    meta = checkpoint.get("metadata", {})
    if meta:
        print(f"[MODEL] Loaded checkpoint: {meta}")
    else:
        print(f"[MODEL] Loaded checkpoint: {path}")

    return model
