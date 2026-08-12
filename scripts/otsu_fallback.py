"""
OrbitalMind — Otsu Threshold Fallback for SAR Flood Detection
==============================================================
Non-ML fallback detector using Otsu's method on the VV change image.
Used when the U-Net mean confidence across the scene is < 0.5
(low-confidence scenes: e.g., partial cloud contamination in optical
validation layer, or very dry pre-event conditions reducing contrast).

Algorithm
---------
1. Load the VV difference image (pre − during, in dB).
2. Flatten to 1-D histogram.
3. Compute Otsu's optimal threshold via ``scipy.ndimage`` or manual
   implementation (no skimage dependency).
4. Binarise: pixels above threshold → flooded (value 1).
5. Save to ``flood_mask_otsu.tif`` alongside the model output.

Usage
-----
    # Standalone (always runs Otsu)
    python scripts/otsu_fallback.py \\
        --vv_diff  data/kerala_2018/vv_diff.tif \\
        --output   data/kerala_2018/flood_mask_otsu.tif

    # Programmatic (called by flood_inference.py when model conf < 0.5)
    from scripts.otsu_fallback import should_use_fallback, apply_otsu_mask

    if should_use_fallback(confidence_map):
        mask = apply_otsu_mask(vv_diff_array, reference_meta, output_path)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_bounds
from scipy import ndimage as ndi

# Repo root for default path resolution
_REPO_ROOT    = Path(__file__).resolve().parents[1]
_DEFAULT_DIFF = _REPO_ROOT / "data" / "kerala_2018" / "vv_diff.tif"
_DEFAULT_OUT  = _REPO_ROOT / "data" / "kerala_2018" / "flood_mask_otsu.tif"

# Confidence threshold below which we prefer the Otsu fallback
CONFIDENCE_THRESHOLD = 0.50


# ---------------------------------------------------------------------------
# Core Otsu implementation (no skimage needed)
# ---------------------------------------------------------------------------

def otsu_threshold(image_array: np.ndarray, n_bins: int = 256) -> float:
    """Compute Otsu's optimal binarisation threshold.

    Uses the between-class variance maximisation formulation.
    Works on any float or integer array.  NaN values are ignored.

    Parameters
    ----------
    image_array : np.ndarray
        1-D or n-D array of pixel values.  Only finite values are used.
    n_bins : int
        Number of histogram bins.  More bins = finer threshold precision.
        Default 256.

    Returns
    -------
    float
        Optimal threshold value in the same units as ``image_array``.

    Algorithm
    ---------
    For each candidate threshold T, compute::

        W0 = fraction of pixels in class 0 (≤ T)
        W1 = fraction of pixels in class 1 (> T)
        M0 = mean of class 0 pixels
        M1 = mean of class 1 pixels
        σ²_B = W0 × W1 × (M0 − M1)²   ← between-class variance

    Return the T that maximises σ²_B.

    Examples
    --------
    >>> arr = np.array([-3.0, -2.5, -2.0, 1.0, 2.0, 3.0])
    >>> t = otsu_threshold(arr)
    >>> -3.0 < t < 3.0
    True
    """
    flat = image_array.ravel()
    flat = flat[np.isfinite(flat)]          # ignore NaN / Inf

    if flat.size == 0:
        raise ValueError("otsu_threshold: input array has no finite values.")

    counts, bin_edges = np.histogram(flat, bins=n_bins)
    bin_centers = 0.5 * (bin_edges[:-1] + bin_edges[1:])

    # Cumulative sums for vectorised Otsu
    total       = counts.sum()
    cum_sum     = np.cumsum(counts)
    cum_mean    = np.cumsum(counts * bin_centers)

    # Global mean
    global_mean = cum_mean[-1] / total

    # Between-class variance for every candidate threshold
    W0 = cum_sum / total                             # weight class 0
    W1 = 1.0 - W0                                   # weight class 1
    M0 = np.where(cum_sum > 0, cum_mean / cum_sum, 0.0)
    M1 = np.where(
        (total - cum_sum) > 0,
        (cum_mean[-1] - cum_mean) / np.maximum(total - cum_sum, 1),
        0.0,
    )

    sigma_b_sq = W0 * W1 * (M0 - M1) ** 2

    # Suppress last bin (W1=0 edge case)
    sigma_b_sq[-1] = 0.0

    best_idx   = int(np.argmax(sigma_b_sq))
    threshold  = float(bin_centers[best_idx])
    return threshold


# ---------------------------------------------------------------------------
# Fallback decision
# ---------------------------------------------------------------------------

def should_use_fallback(confidence_map: np.ndarray) -> bool:
    """Return True if mean model confidence is below the fallback threshold.

    Ignores NaN values (patches with no predicted flood).

    Parameters
    ----------
    confidence_map : np.ndarray
        2-D array of per-pixel sigmoid probabilities from the U-Net,
        or per-patch mean confidences (any shape of floats 0–1 or NaN).

    Returns
    -------
    bool
        ``True`` if the scene-wide mean confidence < ``CONFIDENCE_THRESHOLD``
        (0.50).  ``False`` if the model is performing well.

    Examples
    --------
    >>> confs = np.array([0.3, 0.4, float('nan'), 0.45])
    >>> should_use_fallback(confs)
    True

    >>> confs = np.array([0.7, 0.8, 0.9])
    >>> should_use_fallback(confs)
    False
    """
    finite_vals = confidence_map[np.isfinite(confidence_map)]
    if finite_vals.size == 0:
        print("[OTSU] No finite confidence values — defaulting to fallback.")
        return True

    mean_conf = float(finite_vals.mean())
    print(f"[OTSU] Scene mean confidence = {mean_conf:.4f} "
          f"(threshold = {CONFIDENCE_THRESHOLD})")

    if mean_conf < CONFIDENCE_THRESHOLD:
        print("[OTSU] Low confidence → activating Otsu fallback.")
        return True
    else:
        print("[OTSU] Confidence OK → using U-Net mask.")
        return False


# ---------------------------------------------------------------------------
# Main fallback pipeline
# ---------------------------------------------------------------------------

def apply_otsu_mask(
    vv_diff: np.ndarray,
    reference_meta: dict,
    output_path: Path,
    morphology_close: bool = True,
    close_iterations: int = 2,
) -> np.ndarray:
    """Apply Otsu thresholding to the VV difference image and save the mask.

    Pipeline
    --------
    1. Compute Otsu's optimal threshold on the VV difference array.
    2. Binarise: pixels **above** threshold = flooded (water backscatter drops
       in flood, so ``vv_diff = pre − during`` produces *positive* values
       in flooded pixels).
    3. Optionally apply binary closing (fills small gaps in the flood mask).
    4. Save as a 1-band uint8 GeoTIFF with the same CRS/transform as the
       input VV images.

    Parameters
    ----------
    vv_diff : np.ndarray
        2-D float32 array ``(H, W)`` = ``VV_pre − VV_during`` in dB.
        Positive values indicate decreased backscatter (likely flood).
    reference_meta : dict
        Rasterio metadata dict from the source SAR image (used for CRS,
        transform, and spatial reference when writing the output GeoTIFF).
    output_path : Path
        Destination path for the binary mask GeoTIFF.
    morphology_close : bool
        If True, apply binary closing (``scipy.ndimage.binary_closing``) to
        remove small holes in the predicted flood extent.
    close_iterations : int
        Number of binary closing iterations.  More = smoother but more
        generous flood extent.

    Returns
    -------
    np.ndarray
        Binary flood mask, shape ``(H, W)``, dtype ``uint8`` (0 or 1).
    """
    print("[OTSU] Computing Otsu threshold on VV difference image …")

    threshold = otsu_threshold(vv_diff)
    print(f"[OTSU] Optimal threshold = {threshold:.4f} dB")

    # Binarise: pre − during > threshold → flooded
    mask = (vv_diff > threshold).astype(np.uint8)

    flooded_px = int(mask.sum())
    total_px   = mask.size
    print(
        f"[OTSU] Flooded pixels: {flooded_px:,} / {total_px:,} "
        f"({100 * flooded_px / total_px:.2f}%)"
    )

    # Morphological closing to fill small holes
    if morphology_close and flooded_px > 0:
        struct = ndi.generate_binary_structure(2, 2)   # 3×3 connectivity
        closed = ndi.binary_closing(
            mask, structure=struct, iterations=close_iterations
        )
        mask = closed.astype(np.uint8)
        print(f"[OTSU] Binary closing applied ({close_iterations} iterations)")

    # Save as GeoTIFF
    output_path.parent.mkdir(parents=True, exist_ok=True)
    out_meta = reference_meta.copy()
    out_meta.update(
        dtype="uint8",
        count=1,
        nodata=255,
    )

    with rasterio.open(output_path, "w", **out_meta) as dst:
        dst.write(mask, 1)
        dst.update_tags(
            1,
            method="otsu",
            threshold=str(threshold),
        )

    size_mb = output_path.stat().st_size / (1024 ** 2)
    print(f"[OTSU] Saved flood mask → {output_path} ({size_mb:.2f} MB)")
    return mask


# ---------------------------------------------------------------------------
# Load VV diff from file + run standalone
# ---------------------------------------------------------------------------

def run_otsu_from_files(vv_diff_path: Path, output_path: Path) -> np.ndarray:
    """Load a VV difference GeoTIFF and run the full Otsu pipeline.

    Convenience wrapper for CLI and programmatic use when the VV diff
    has already been written to disk by ``flood_inference.py``.

    Parameters
    ----------
    vv_diff_path : Path
        Path to the VV difference GeoTIFF (1-band float32).
    output_path : Path
        Destination path for the Otsu flood mask GeoTIFF.

    Returns
    -------
    np.ndarray
        Binary flood mask, shape ``(H, W)``, uint8.
    """
    if not vv_diff_path.exists():
        raise FileNotFoundError(
            f"VV diff file not found: {vv_diff_path}\n"
            "Run flood_inference.py first to generate vv_diff.tif."
        )

    print(f"[OTSU] Loading VV diff: {vv_diff_path}")
    with rasterio.open(vv_diff_path) as src:
        vv_diff = src.read(1).astype(np.float32)
        meta    = src.meta.copy()

    print(f"[OTSU] VV diff shape: {vv_diff.shape}, "
          f"range: [{vv_diff.min():.2f}, {vv_diff.max():.2f}] dB")

    return apply_otsu_mask(vv_diff, meta, output_path)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Otsu fallback flood detection from VV difference GeoTIFF"
    )
    parser.add_argument(
        "--vv_diff",
        type=Path,
        default=_DEFAULT_DIFF,
        help=f"Path to VV difference GeoTIFF (default: {_DEFAULT_DIFF})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=_DEFAULT_OUT,
        help=f"Output mask path (default: {_DEFAULT_OUT})",
    )
    parser.add_argument(
        "--no-close",
        action="store_true",
        help="Disable morphological closing post-processing",
    )
    args = parser.parse_args()

    mask = run_otsu_from_files(args.vv_diff, args.output)
    flooded_pct = 100 * mask.sum() / mask.size
    print(f"\n[DONE] Otsu flood mask written to: {args.output}")
    print(f"       Flooded area: {flooded_pct:.2f}% of scene")
