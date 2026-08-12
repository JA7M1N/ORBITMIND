"""
OrbitalMind — Flood Inference Pipeline
=======================================
Full end-to-end pipeline: SAR GeoTIFFs → Attention U-Net → flood_mask.tif

Pipeline stages
---------------
1. Load pre-flood and during-flood Sentinel-1 GeoTIFFs (rasterio)
2. Normalise per-band (zero-mean, unit-std from training stats)
3. Compute VV difference image (pre − during, dB) → vv_diff.tif
4. Tile the 2-band SAR stack into 256×256 patches (32px overlap)
5. Batch-run Attention U-Net (FP16, batch size 8) → per-patch sigmoid probs
6. Stitch patches back using weighted averaging (overlap regions averaged)
7. Apply SRTM slope mask: slope > 5° → flood probability forced to 0
8. Check scene confidence; call Otsu fallback if mean_confidence < 0.5
9. Binarise at threshold 0.5 → flood_mask.tif (uint8)
10. Export confidence_map.tif (float32, 0–1)
11. Vectorise flood mask → flood_mask.geojson (for demo_data loader)
12. Print: total flooded area km², average confidence, tiles processed

Output directory layout
------------------------
data/kerala_2018/
├── vv_diff.tif           (float32) VV change image
├── confidence_map.tif    (float32) raw sigmoid probabilities
├── flood_mask.tif        (uint8)   binary flood mask
└── flood_mask_otsu.tif   (uint8)   Otsu fallback (generated if conf < 0.5)

backend/demo_data/flood/kerala_2018/
└── flood_mask.geojson    (GeoJSON FeatureCollection for demo loader)

Usage
-----
    # With a pre-trained model checkpoint:
    python ml/inference/flood_inference.py \\
        --pre    data/kerala_2018/s1_pre_flood.tif \\
        --during data/kerala_2018/s1_during_flood.tif \\
        --dem    data/kerala_2018/srtm_dem.tif \\
        --model  checkpoints/flood_unet_best.pt \\
        --output data/kerala_2018

    # Without checkpoint (untrained model — for pipeline testing only):
    python ml/inference/flood_inference.py --no-checkpoint
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import warnings
from pathlib import Path
from typing import Optional

import numpy as np
import rasterio
from rasterio.features import shapes as rasterio_shapes
from rasterio.transform import from_bounds
import torch

# ---------------------------------------------------------------------------
# Repo root & default paths
# ---------------------------------------------------------------------------
_REPO_ROOT      = Path(__file__).resolve().parents[2]   # OrbitalMind/
_DEFAULT_PRE    = _REPO_ROOT / "data" / "kerala_2018" / "s1_pre_flood.tif"
_DEFAULT_DURING = _REPO_ROOT / "data" / "kerala_2018" / "s1_during_flood.tif"
_DEFAULT_DEM    = _REPO_ROOT / "data" / "kerala_2018" / "srtm_dem.tif"
_DEFAULT_OUT    = _REPO_ROOT / "data" / "kerala_2018"
_DEMO_OUT       = _REPO_ROOT / "backend" / "demo_data" / "flood" / "kerala_2018"
_DEFAULT_CKPT   = _REPO_ROOT / "checkpoints" / "flood_unet_best.pt"

# ---------------------------------------------------------------------------
# Per-band normalisation statistics (WorldFloods v2 training set stats)
# Adjust after fine-tuning on Kerala data.
# ---------------------------------------------------------------------------
# Format: {band_idx: (mean_dB, std_dB)}
SAR_NORM_STATS: dict[int, tuple[float, float]] = {
    0: (-12.0, 4.5),   # VV band
    1: (-18.5, 4.0),   # VH band
}


# ---------------------------------------------------------------------------
# 1. I/O helpers
# ---------------------------------------------------------------------------

def load_sar_image(path: Path) -> tuple[np.ndarray, dict]:
    """Load a multi-band SAR GeoTIFF into a float32 numpy array.

    Parameters
    ----------
    path : Path
        Path to a GeoTIFF with ``C`` bands (e.g. VV=1, VH=2).

    Returns
    -------
    array : np.ndarray
        Shape ``(C, H, W)``, dtype float32.
    meta : dict
        Rasterio metadata dict (crs, transform, dtype, width, height, count).

    Raises
    ------
    FileNotFoundError
        If the GeoTIFF does not exist.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"SAR image not found: {path}\n"
            "Run scripts/gee_data_pull.py first."
        )
    with rasterio.open(path) as src:
        array = src.read().astype(np.float32)   # (C, H, W)
        meta  = src.meta.copy()
    return array, meta


def load_dem(dem_path: Path, target_shape: tuple[int, int], target_meta: dict) -> np.ndarray:
    """Load and reproject the SRTM DEM to match the SAR image shape.

    Uses nearest-neighbour resampling (appropriate for DEM upscaling).
    If the DEM already matches ``target_shape``, no resampling is performed.

    Parameters
    ----------
    dem_path : Path
        Path to the SRTM DEM GeoTIFF (1 band, elevation in metres).
    target_shape : tuple[int, int]
        ``(height, width)`` of the SAR image to match.
    target_meta : dict
        Rasterio meta from the SAR image (used for transform / CRS).

    Returns
    -------
    np.ndarray
        Shape ``(H, W)``, float32, elevation in metres.
    """
    if not dem_path.exists():
        print(f"[WARN] DEM not found at {dem_path} — slope mask disabled.")
        H, W = target_shape
        return np.zeros((H, W), dtype=np.float32)

    with rasterio.open(dem_path) as src:
        dem = src.read(1).astype(np.float32)

    H_sar, W_sar = target_shape
    H_dem, W_dem = dem.shape

    if (H_dem, W_dem) != (H_sar, W_sar):
        # Simple nearest-neighbour resize using numpy (avoids cv2 dependency)
        row_idx = np.round(np.linspace(0, H_dem - 1, H_sar)).astype(int)
        col_idx = np.round(np.linspace(0, W_dem - 1, W_sar)).astype(int)
        dem = dem[np.ix_(row_idx, col_idx)]
        print(
            f"[DEM]  Resampled DEM {H_dem}×{W_dem} → {H_sar}×{W_sar} (nearest)"
        )

    return dem


def save_geotiff(
    array: np.ndarray,
    output_path: Path,
    reference_meta: dict,
    dtype: str = "float32",
    nodata: Optional[float] = None,
    band_tags: dict = None,
) -> None:
    """Write a numpy array to a single-band GeoTIFF.

    Parameters
    ----------
    array : np.ndarray
        2-D array ``(H, W)`` to write.
    output_path : Path
        Destination file path (parent directories created if absent).
    reference_meta : dict
        Rasterio metadata from a reference image (for CRS and transform).
    dtype : str
        Output dtype string (e.g. ``"float32"``, ``"uint8"``).
    nodata : float, optional
        NoData value for the output band.
    band_tags : dict, optional
        Key-value tags written to band 1 metadata.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    meta = reference_meta.copy()
    meta.update(count=1, dtype=dtype)
    if nodata is not None:
        meta["nodata"] = nodata

    with rasterio.open(output_path, "w", **meta) as dst:
        dst.write(array.astype(dtype), 1)
        if band_tags:
            dst.update_tags(1, **band_tags)

    size_mb = output_path.stat().st_size / (1024 ** 2)
    print(f"[IO]   Saved {output_path.name} ({size_mb:.2f} MB)")


# ---------------------------------------------------------------------------
# 2. Pre-processing
# ---------------------------------------------------------------------------

def normalise_sar(sar_array: np.ndarray) -> np.ndarray:
    """Per-band zero-mean, unit-std normalisation using WorldFloods stats.

    Parameters
    ----------
    sar_array : np.ndarray
        Shape ``(C, H, W)`` — raw SAR dB values.

    Returns
    -------
    np.ndarray
        Normalised array, same shape, float32.
    """
    out = np.empty_like(sar_array, dtype=np.float32)
    for c in range(sar_array.shape[0]):
        mean, std = SAR_NORM_STATS.get(c, (0.0, 1.0))
        out[c] = (sar_array[c] - mean) / (std + 1e-8)
    return out


def compute_vv_difference(
    pre_array: np.ndarray,
    during_array: np.ndarray,
) -> np.ndarray:
    """Compute VV change image: pre − during (in dB).

    Flood backscatter drops significantly in Sentinel-1 VV during inundation
    (double-bounce from open water → specular reflection away from sensor).
    Therefore ``pre − during > 0`` marks flooded pixels.

    Parameters
    ----------
    pre_array : np.ndarray
        Shape ``(C, H, W)`` — pre-flood SAR stack (VV=0, VH=1).
    during_array : np.ndarray
        Shape ``(C, H, W)`` — during-flood SAR stack.

    Returns
    -------
    np.ndarray
        Shape ``(H, W)`` float32, VV channel change image.
    """
    vv_pre    = pre_array[0].astype(np.float32)
    vv_during = during_array[0].astype(np.float32)
    diff      = vv_pre - vv_during
    print(
        f"[PRE]  VV diff range: [{diff.min():.2f}, {diff.max():.2f}] dB  "
        f"mean={diff.mean():.2f}"
    )
    return diff


# ---------------------------------------------------------------------------
# 3. Tiling
# ---------------------------------------------------------------------------

def tile_image(
    image: np.ndarray,
    patch_size: int = 256,
    overlap: int = 32,
) -> list[tuple[np.ndarray, tuple[int, int, int, int]]]:
    """Tile a multi-band image into overlapping 256×256 patches.

    Edge tiles are zero-padded to ``patch_size`` so every patch fed to the
    model has exactly the expected spatial dimensions.

    Parameters
    ----------
    image : np.ndarray
        Shape ``(C, H, W)`` — multi-band image.
    patch_size : int
        Patch height and width in pixels. Default 256.
    overlap : int
        Overlap in pixels between adjacent patches. Default 32.
        Stride = ``patch_size − overlap`` = 224.

    Returns
    -------
    list of (patch, bbox)
        - ``patch``  — shape ``(C, patch_size, patch_size)``, float32
        - ``bbox``   — ``(r0, c0, r1, c1)`` actual pixel bounds in the
          original image (before padding)

    Notes
    -----
    Stride = patch_size − overlap = 224 pixels.
    For a 2775×2725 image: ⌈2775/224⌉ × ⌈2725/224⌉ ≈ 154 tiles.
    """
    C, H, W = image.shape
    stride  = patch_size - overlap
    tiles   = []

    for r0 in range(0, H, stride):
        for c0 in range(0, W, stride):
            r1 = min(r0 + patch_size, H)   # actual end row (may be < r0+256)
            c1 = min(c0 + patch_size, W)

            patch = image[:, r0:r1, c0:c1].copy()  # (C, ph, pw)

            # Zero-pad to patch_size if edge tile
            ph, pw = patch.shape[1], patch.shape[2]
            if ph < patch_size or pw < patch_size:
                pad = np.zeros((C, patch_size, patch_size), dtype=np.float32)
                pad[:, :ph, :pw] = patch
                patch = pad

            tiles.append((patch, (r0, c0, r1, c1)))

    return tiles


# ---------------------------------------------------------------------------
# 4. Stitching (weighted average in overlap zones)
# ---------------------------------------------------------------------------

def stitch_patches(
    predictions: list[tuple[np.ndarray, tuple[int, int, int, int]]],
    H: int,
    W: int,
) -> np.ndarray:
    """Reconstruct a full-resolution confidence map from overlapping patches.

    Uses weighted averaging in overlap regions (each patch contributes equally).
    This removes the blocky seam artefacts that appear with simple assignment.

    Parameters
    ----------
    predictions : list of (prob_map, bbox)
        - ``prob_map`` — shape ``(H_patch, W_patch)`` float32, sigmoid probabilities
        - ``bbox``     — ``(r0, c0, r1, c1)`` in the original image
    H : int
        Original image height.
    W : int
        Original image width.

    Returns
    -------
    np.ndarray
        Shape ``(H, W)`` float32, averaged sigmoid probabilities.
        Guaranteed to have every pixel covered (no zeros from missing tiles).
    """
    acc_prob  = np.zeros((H, W), dtype=np.float64)   # accumulator
    acc_count = np.zeros((H, W), dtype=np.float64)   # vote count

    for prob_map, (r0, c0, r1, c1) in predictions:
        ph = r1 - r0   # actual height (before padding)
        pw = c1 - c0   # actual width

        acc_prob [r0:r1, c0:c1] += prob_map[:ph, :pw].astype(np.float64)
        acc_count[r0:r1, c0:c1] += 1.0

    # Avoid division by zero (should never happen if tiling is correct)
    acc_count = np.maximum(acc_count, 1e-9)
    return (acc_prob / acc_count).astype(np.float32)


# ---------------------------------------------------------------------------
# 5. SRTM slope mask
# ---------------------------------------------------------------------------

def compute_slope_mask(
    dem: np.ndarray,
    pixel_size_m: float = 30.0,
    slope_threshold_deg: float = 5.0,
) -> np.ndarray:
    """Compute a binary mask where terrain slope exceeds ``slope_threshold_deg``.

    Flood water cannot pool on slopes > 5°; masking these pixels removes
    false positives on hillsides and mountain foothills.

    Parameters
    ----------
    dem : np.ndarray
        Shape ``(H, W)`` — elevation in metres (SRTM).
    pixel_size_m : float
        Ground sampling distance in metres per pixel. Default 30m (SRTM).
    slope_threshold_deg : float
        Slope threshold in degrees. Pixels above this → masked (value 0).
        Default 5°.

    Returns
    -------
    np.ndarray
        Shape ``(H, W)`` uint8 — 1 where slope ≤ threshold (keep),
        0 where slope > threshold (mask out / cannot be flood).
    """
    # Gradient in pixel units → convert to metres using pixel_size_m
    dz_dy, dz_dx = np.gradient(dem, pixel_size_m, pixel_size_m)
    slope_rad     = np.arctan(np.sqrt(dz_dx ** 2 + dz_dy ** 2))
    slope_deg     = np.degrees(slope_rad)

    mask = (slope_deg <= slope_threshold_deg).astype(np.uint8)
    masked_pct = 100 * (1 - mask.mean())
    print(
        f"[SLOPE] Slope mask: {masked_pct:.1f}% of pixels excluded "
        f"(slope > {slope_threshold_deg}°)"
    )
    return mask


# ---------------------------------------------------------------------------
# 6. Vectorisation (flood mask → GeoJSON FeatureCollection)
# ---------------------------------------------------------------------------

def vectorise_flood_mask(
    flood_mask: np.ndarray,
    confidence_map: np.ndarray,
    reference_meta: dict,
    min_area_km2: float = 0.01,
) -> dict:
    """Convert a binary flood mask to a GeoJSON FeatureCollection.

    Uses ``rasterio.features.shapes`` to extract connected flood polygons.
    Each polygon feature includes ``confidence`` and ``area_km2`` properties
    used by the priority scoring engine.

    Parameters
    ----------
    flood_mask : np.ndarray
        Shape ``(H, W)`` uint8 — 1 = flooded, 0 = dry.
    confidence_map : np.ndarray
        Shape ``(H, W)`` float32 — U-Net sigmoid probability per pixel.
    reference_meta : dict
        Rasterio metadata (for CRS and transform).
    min_area_km2 : float
        Minimum polygon area to include. Smaller polygons are filtered out
        as noise. Default 0.01 km².

    Returns
    -------
    dict
        GeoJSON FeatureCollection with flood polygons.
    """
    from rasterio.crs import CRS  # local import to keep top-level imports clean

    transform = reference_meta["transform"]
    pixel_area_km2 = abs(transform.a * transform.e) * (111.0 ** 2)  # approx

    features = []
    for geom, val in rasterio_shapes(flood_mask, transform=transform):
        if val != 1:
            continue

        # Compute polygon bounds to extract confidence stats
        coords    = geom["coordinates"][0]
        lons      = [c[0] for c in coords]
        lats      = [c[1] for c in coords]
        min_lon, max_lon = min(lons), max(lons)
        min_lat, max_lat = min(lats), max(lats)

        # Approximate area (simple pixel count in bounding box)
        meta_h = reference_meta["height"]
        meta_w = reference_meta["width"]
        bbox_h = max(1, int((max_lat - min_lat) / abs(transform.e)))
        bbox_w = max(1, int((max_lon - min_lon) / abs(transform.a)))
        area_km2 = bbox_h * bbox_w * pixel_area_km2

        if area_km2 < min_area_km2:
            continue

        # Mean confidence within the polygon bounding box
        r0 = max(0, int((reference_meta["transform"].f - max_lat) / abs(transform.e)))
        c0 = max(0, int((min_lon - reference_meta["transform"].c) / transform.a))
        r1 = min(meta_h, r0 + bbox_h)
        c1 = min(meta_w, c0 + bbox_w)

        patch_conf = confidence_map[r0:r1, c0:c1]
        mean_conf  = float(patch_conf[patch_conf > 0].mean()) if patch_conf.any() else 0.0

        features.append(
            {
                "type": "Feature",
                "geometry": geom,
                "properties": {
                    "confidence": round(mean_conf, 4),
                    "area_km2":   round(area_km2, 4),
                    "disaster_type": "flood",
                    "source":        "unet_inference",
                },
            }
        )

    geojson = {
        "type":     "FeatureCollection",
        "features": features,
    }
    print(f"[VEC]  Vectorised {len(features)} flood polygon(s) "
          f"(min_area={min_area_km2} km²)")
    return geojson


# ---------------------------------------------------------------------------
# 7. Main inference orchestrator
# ---------------------------------------------------------------------------

def run_flood_inference(
    pre_path:     Path,
    during_path:  Path,
    dem_path:     Path,
    output_dir:   Path,
    model_path:   Optional[Path] = None,
    batch_size:   int = 8,
    patch_size:   int = 256,
    overlap:      int = 32,
    slope_thresh: float = 5.0,
    demo_out_dir: Optional[Path] = None,
) -> dict:
    """Run the complete Sentinel-1 flood detection inference pipeline.

    Stages
    ------
    1. Load SAR GeoTIFFs
    2. Normalise bands
    3. Compute VV difference → vv_diff.tif
    4. Tile into 256×256 patches (32px overlap)
    5. Run U-Net FP16 inference (batch size 8)
    6. Stitch patches → full-resolution confidence map
    7. Apply SRTM slope mask
    8. Check confidence; Otsu fallback if mean < 0.5
    9. Binarise → flood_mask.tif
    10. Export confidence_map.tif
    11. Vectorise → flood_mask.geojson
    12. Print summary stats

    Parameters
    ----------
    pre_path : Path
        Pre-flood Sentinel-1 GeoTIFF (VV+VH, 2-band).
    during_path : Path
        During-flood Sentinel-1 GeoTIFF (VV+VH, 2-band).
    dem_path : Path
        SRTM DEM GeoTIFF (1-band, elevation metres).
    output_dir : Path
        Directory for intermediate and final output GeoTIFFs.
    model_path : Path, optional
        Path to U-Net checkpoint (.pt).  If ``None`` or not found, an
        untrained model is used (for pipeline testing only).
    batch_size : int
        Patches per forward pass. Default 8.
    patch_size : int
        Tile size in pixels. Default 256.
    overlap : int
        Overlap between adjacent tiles in pixels. Default 32.
    slope_thresh : float
        Slope threshold in degrees for the SRTM mask. Default 5.0°.
    demo_out_dir : Path, optional
        If provided, ``flood_mask.geojson`` is also written here (for
        the demo_data loader).

    Returns
    -------
    dict
        Pipeline result summary::

            {
                "event_id":      str,
                "disaster_type": "flood",
                "source":        "unet_inference",
                "affected_zones": <GeoJSON FeatureCollection>,
                "summary_stats": {
                    "total_area_km2":  float,
                    "mean_confidence": float,
                    "peak_intensity":  float,
                    "tiles_processed": int,
                    "used_otsu":       bool,
                },
            }
    """
    t_start = time.perf_counter()
    output_dir.mkdir(parents=True, exist_ok=True)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"\n{'='*60}")
    print(f"  OrbitalMind — Flood Inference Pipeline")
    print(f"{'='*60}")
    print(f"  Device : {device}")
    print(f"  Batch  : {batch_size} patches")
    print(f"  Tiles  : {patch_size}×{patch_size}px, {overlap}px overlap\n")

    # ------------------------------------------------------------------
    # Stage 1: Load SAR data
    # ------------------------------------------------------------------
    print("[1/9] Loading SAR GeoTIFFs …")
    pre_array,    sar_meta = load_sar_image(pre_path)
    during_array, _        = load_sar_image(during_path)

    C, H, W = pre_array.shape
    print(f"      Image shape: {C} bands × {H} × {W} px")

    # ------------------------------------------------------------------
    # Stage 2: Normalise
    # ------------------------------------------------------------------
    print("[2/9] Normalising SAR bands …")
    pre_norm    = normalise_sar(pre_array)
    during_norm = normalise_sar(during_array)

    # 2-band stack: (2, H, W)
    # Stack pre and during VV+VH into 2-channel: VV_pre, VV_during? 
    # Architecture: in_channels=2 — use (VV, VH) from the DURING image
    # augmented with the VV difference as supplementary context.
    # Convention here: channel 0 = VV_during normalised,
    #                  channel 1 = VV_diff (change feature)
    vv_diff = compute_vv_difference(pre_array, during_array)
    input_stack = np.stack([during_norm[0], vv_diff], axis=0)  # (2, H, W)

    # ------------------------------------------------------------------
    # Stage 3: Save VV diff image
    # ------------------------------------------------------------------
    print("[3/9] Saving VV difference image …")
    save_geotiff(
        vv_diff,
        output_dir / "vv_diff.tif",
        sar_meta,
        dtype="float32",
        band_tags={"description": "VV_pre - VV_during (dB)"},
    )

    # ------------------------------------------------------------------
    # Stage 4: Load model
    # ------------------------------------------------------------------
    print("[4/9] Loading Attention U-Net …")
    from ml.models.flood_unet import build_flood_unet, load_model, process_patches

    use_pretrained = model_path is not None and Path(model_path).exists()
    if use_pretrained:
        model = load_model(model_path, device=device)
        print(f"      Checkpoint: {model_path}")
    else:
        warnings.warn(
            "No model checkpoint provided or found — using untrained weights. "
            "Results will be random. Download a checkpoint or train the model first.",
            UserWarning,
            stacklevel=2,
        )
        model = build_flood_unet(encoder_weights=None).to(device).eval()
        print("      [WARN] Untrained model — for pipeline testing only")

    # ------------------------------------------------------------------
    # Stage 5: Tile image
    # ------------------------------------------------------------------
    print("[5/9] Tiling image …")
    tiles = tile_image(input_stack, patch_size=patch_size, overlap=overlap)
    n_tiles = len(tiles)
    print(f"      Generated {n_tiles} tiles "
          f"({patch_size}×{patch_size}px, stride={(patch_size - overlap)}px)")

    # ------------------------------------------------------------------
    # Stage 6: Batch inference
    # ------------------------------------------------------------------
    print(f"[6/9] Running U-Net inference (batch={batch_size}, device={device}) …")
    patch_arrays = [t[0] for t in tiles]
    patch_bounds = [t[1] for t in tiles]

    # Convert to tensors for process_patches
    import torch
    masks_raw, confidences = process_patches(model, patch_arrays, batch_size=batch_size, device=device)

    # process_patches returns binary masks; we need raw probabilities for stitching.
    # Re-run to get probabilities (build a small wrapper):
    #   Actually, process_patches already returns (masks, confidences) where masks
    #   are binary and confidences are per-patch means. For stitching we need
    #   per-pixel probabilities. Let's do a second pass to get probs.

    # Re-run model to get sigmoid probability maps (not binary)
    model.eval()
    prob_maps: list[np.ndarray] = []

    n_batches = (n_tiles + batch_size - 1) // batch_size
    print(f"      Collecting probability maps ({n_batches} batches) …")

    for b in range(n_batches):
        s = b * batch_size
        e = min(s + batch_size, n_tiles)
        batch_tensors = [
            torch.from_numpy(patch_arrays[i].astype(np.float32))
            for i in range(s, e)
        ]
        batch = torch.stack(batch_tensors).to(device, dtype=torch.float32)

        with torch.no_grad():
            with torch.cuda.amp.autocast(enabled=device.type == "cuda"):
                logits = model(batch)

        probs = torch.sigmoid(logits).squeeze(1).cpu().float().numpy()  # (B, H, W)
        for prob in probs:
            prob_maps.append(prob)

        print(f"\r      Batch {b+1}/{n_batches} complete …", end="", flush=True)

    print()

    # Clear GPU memory before Ollama can be loaded
    del model
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    print("      GPU memory cleared (Ollama can now be loaded)")

    # ------------------------------------------------------------------
    # Stage 7: Stitch patches
    # ------------------------------------------------------------------
    print("[7/9] Stitching patches …")
    predictions = list(zip(prob_maps, patch_bounds))
    confidence_map = stitch_patches(predictions, H, W)
    print(f"      Full-res confidence map: {confidence_map.shape}, "
          f"range=[{confidence_map.min():.3f}, {confidence_map.max():.3f}]")

    # ------------------------------------------------------------------
    # Stage 7b: Apply SRTM slope mask
    # ------------------------------------------------------------------
    print("[7b/9] Applying SRTM slope mask …")
    dem = load_dem(dem_path, target_shape=(H, W), target_meta=sar_meta)
    slope_mask = compute_slope_mask(dem, pixel_size_m=30.0, slope_threshold_deg=slope_thresh)
    confidence_map *= slope_mask   # zero out steep terrain

    # ------------------------------------------------------------------
    # Stage 8: Confidence check → Otsu fallback
    # ------------------------------------------------------------------
    print("[8/9] Checking scene confidence …")
    finite_confs = [c for c in confidences if not np.isnan(c)]
    mean_scene_conf = float(np.mean(finite_confs)) if finite_confs else 0.0
    print(f"      Scene mean confidence = {mean_scene_conf:.4f}")

    used_otsu = False
    if mean_scene_conf < 0.5:
        print("      Low confidence — activating Otsu fallback …")
        from scripts.otsu_fallback import apply_otsu_mask
        otsu_mask = apply_otsu_mask(
            vv_diff      = vv_diff,
            reference_meta = sar_meta,
            output_path    = output_dir / "flood_mask_otsu.tif",
        )
        # Blend: use Otsu where U-Net confidence is very low
        flood_mask = otsu_mask
        used_otsu  = True
    else:
        flood_mask = (confidence_map > 0.5).astype(np.uint8)

    # ------------------------------------------------------------------
    # Stage 9: Save outputs
    # ------------------------------------------------------------------
    print("[9/9] Saving output GeoTIFFs …")

    save_geotiff(
        confidence_map,
        output_dir / "confidence_map.tif",
        sar_meta,
        dtype="float32",
        nodata=-9999.0,
        band_tags={"description": "U-Net sigmoid flood probability"},
    )

    save_geotiff(
        flood_mask,
        output_dir / "flood_mask.tif",
        sar_meta,
        dtype="uint8",
        nodata=255,
        band_tags={
            "description": "Binary flood mask (1=flood, 0=dry)",
            "method":      "otsu" if used_otsu else "unet",
        },
    )

    # ------------------------------------------------------------------
    # Vectorise → GeoJSON
    # ------------------------------------------------------------------
    print("[VEC]  Vectorising flood mask to GeoJSON …")
    geojson = vectorise_flood_mask(flood_mask, confidence_map, sar_meta)

    # Write to output_dir
    geojson_path = output_dir / "flood_mask.geojson"
    with geojson_path.open("w", encoding="utf-8") as fh:
        json.dump(geojson, fh, indent=2)
    print(f"[IO]   Saved {geojson_path.name}")

    # Write to demo_data dir (for demo loader)
    if demo_out_dir is not None:
        demo_out_dir.mkdir(parents=True, exist_ok=True)
        demo_geojson_path = demo_out_dir / "flood_mask.geojson"
        with demo_geojson_path.open("w", encoding="utf-8") as fh:
            json.dump(geojson, fh, indent=2)
        print(f"[DEMO] Copied to demo_data: {demo_geojson_path}")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    pixel_area_km2 = abs(sar_meta["transform"].a * sar_meta["transform"].e) * (111.0 ** 2)
    total_area_km2 = float(flood_mask.sum()) * pixel_area_km2
    peak_intensity = float(confidence_map.max())
    elapsed        = time.perf_counter() - t_start

    print(f"\n{'='*60}")
    print(f"  Flood Inference Complete  ({elapsed:.1f}s)")
    print(f"{'='*60}")
    print(f"  Tiles processed   : {n_tiles}")
    print(f"  Flooded area      : {total_area_km2:.2f} km²")
    print(f"  Mean confidence   : {mean_scene_conf:.4f}")
    print(f"  Peak intensity    : {peak_intensity:.4f}")
    print(f"  Otsu fallback     : {'YES' if used_otsu else 'no'}")
    print(f"  Output dir        : {output_dir}")
    print(f"{'='*60}\n")

    return {
        "event_id":       "kerala_2018",
        "disaster_type":  "flood",
        "source":         "unet_inference",
        "affected_zones": geojson,
        "summary_stats":  {
            "total_area_km2":  round(total_area_km2, 2),
            "mean_confidence": round(mean_scene_conf, 4),
            "peak_intensity":  round(peak_intensity, 4),
            "tiles_processed": n_tiles,
            "used_otsu":       used_otsu,
        },
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="OrbitalMind — Flood Inference Pipeline (Sentinel-1 → U-Net)"
    )
    parser.add_argument("--pre",    type=Path, default=_DEFAULT_PRE,    help="Pre-flood SAR GeoTIFF")
    parser.add_argument("--during", type=Path, default=_DEFAULT_DURING, help="During-flood SAR GeoTIFF")
    parser.add_argument("--dem",    type=Path, default=_DEFAULT_DEM,    help="SRTM DEM GeoTIFF")
    parser.add_argument("--model",  type=Path, default=_DEFAULT_CKPT,   help="Model checkpoint .pt")
    parser.add_argument("--output", type=Path, default=_DEFAULT_OUT,    help="Output directory")
    parser.add_argument("--batch",  type=int,  default=8,               help="Batch size (default 8)")
    parser.add_argument(
        "--no-checkpoint",
        action="store_true",
        help="Run with untrained model weights (pipeline test only)",
    )
    args = parser.parse_args()

    model_path = None if args.no_checkpoint else args.model

    result = run_flood_inference(
        pre_path     = args.pre,
        during_path  = args.during,
        dem_path     = args.dem,
        output_dir   = args.output,
        model_path   = model_path,
        batch_size   = args.batch,
        demo_out_dir = _DEMO_OUT,
    )

    sys.exit(0)
