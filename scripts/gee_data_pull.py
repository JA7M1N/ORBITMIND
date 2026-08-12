"""
OrbitalMind — Sentinel-1 SAR Data Acquisition via Google Earth Engine
=======================================================================
Downloads pre-flood and during-flood Sentinel-1 GRD composites and the
SRTM DEM for Kerala 2018 Flood analysis.

Output directory layout
-----------------------
data/
└── kerala_2018/
    ├── s1_pre_flood.tif    (2-band: VV, VH)  2018-06-01 → 2018-06-30
    ├── s1_during_flood.tif (2-band: VV, VH)  2018-08-01 → 2018-08-31
    └── srtm_dem.tif        (1-band: elev m)  SRTM 30m

Usage
-----
    python scripts/gee_data_pull.py
    python scripts/gee_data_pull.py --scale 60      # faster download
    python scripts/gee_data_pull.py --output data/custom_dir

Requirements
------------
    pip install earthengine-api rasterio requests numpy
    earthengine authenticate   ← one-time browser auth

Notes
-----
- GEE getDownloadURL has a ~50 MB per-band limit; use --scale 60 (default)
  if the 30m download is rejected. The inference pipeline handles any scale.
- For production 10m-resolution runs, switch to ee.batch.Export.image.toDrive()
  (see export_to_drive() helper at the bottom of this file).
- Speckle filter: 5×5 boxcar (focalMean, radius=2, kernel=square).
"""

from __future__ import annotations

import argparse
import io
import os
import sys
import time
import zipfile
from pathlib import Path

import numpy as np
import requests
import rasterio
from rasterio.transform import from_bounds

# ---------------------------------------------------------------------------
# Repo root and output defaults
# ---------------------------------------------------------------------------
_REPO_ROOT   = Path(__file__).resolve().parents[1]
_DEFAULT_OUT = _REPO_ROOT / "data" / "kerala_2018"

# Kerala 2018 Flood — bounding box [min_lon, min_lat, max_lon, max_lat]
KERALA_BBOX = [76.0, 9.5, 77.5, 11.0]

# Date windows
PRE_FLOOD_START    = "2018-06-01"
PRE_FLOOD_END      = "2018-06-30"
DURING_FLOOD_START = "2018-08-01"
DURING_FLOOD_END   = "2018-08-31"


# ---------------------------------------------------------------------------
# GEE helpers
# ---------------------------------------------------------------------------

def authenticate_gee() -> None:
    """Authenticate and initialise the GEE Python API.

    Uses cached credentials from ``~/.config/earthengine/credentials`` if
    available.  On first run the function opens a browser for OAuth consent.

    Raises
    ------
    SystemExit
        If the ``earthengine-api`` package is not installed.
    """
    try:
        import ee  # type: ignore[import]
    except ImportError:
        print("[ERROR] earthengine-api not installed. Run: pip install earthengine-api")
        sys.exit(1)

    print("[GEE] Authenticating … ", end="", flush=True)
    try:
        ee.Initialize()
        print("OK (cached credentials)")
    except Exception:
        print()
        print("[GEE] No cached credentials — launching browser auth …")
        ee.Authenticate()
        ee.Initialize()
        print("[GEE] Authenticated and initialised.")


def bbox_to_ee_region(bbox: list[float]):
    """Convert ``[min_lon, min_lat, max_lon, max_lat]`` to a GEE Geometry.

    Parameters
    ----------
    bbox : list[float]
        ``[west, south, east, north]`` in EPSG:4326.

    Returns
    -------
    ee.Geometry.Rectangle
    """
    import ee  # type: ignore[import]
    west, south, east, north = bbox
    return ee.Geometry.Rectangle([west, south, east, north])


def apply_speckle_filter(image) -> object:
    """Apply a 5×5 boxcar (mean) speckle filter to a Sentinel-1 image.

    The boxcar filter suppresses multiplicative SAR speckle by averaging a
    5×5 neighbourhood.  ``focalMean`` with ``radius=2, units='pixels'`` and
    ``kernelType='square'`` produces a 5×5 kernel (radius 2 → diameter 5).

    Parameters
    ----------
    image : ee.Image
        Sentinel-1 GRD image with VV and/or VH bands (linear scale).

    Returns
    -------
    ee.Image
        Speckle-filtered image, same bands and projection as input.
    """
    # focalMean: radius in pixels, square kernel = boxcar
    return image.focalMean(radius=2, kernelType="square", units="pixels")


def get_sentinel1_composite(
    region,
    start_date: str,
    end_date: str,
    label: str = "",
) -> object:
    """Build a Sentinel-1 GRD VV+VH composite for the given region and dates.

    Filters the ``COPERNICUS/S1_GRD`` collection to:
    - IW mode (Interferometric Wide swath)
    - VV + VH dual polarisation
    - Descending orbit (most consistent for India)

    Then applies a 5×5 boxcar speckle filter and returns the median composite.

    Parameters
    ----------
    region : ee.Geometry
        Area of interest.
    start_date : str
        ISO-8601 start date (inclusive), e.g. ``"2018-06-01"``.
    end_date : str
        ISO-8601 end date (exclusive), e.g. ``"2018-06-30"``.
    label : str
        Human-readable label printed in progress messages.

    Returns
    -------
    ee.Image
        Two-band image with ``VV`` and ``VH`` bands (dB scale, Float32).

    Raises
    ------
    RuntimeError
        If the filtered collection is empty (no imagery for the given params).
    """
    import ee  # type: ignore[import]

    print(f"[GEE] Building Sentinel-1 composite: {label} ({start_date} → {end_date})")

    collection = (
        ee.ImageCollection("COPERNICUS/S1_GRD")
        .filterBounds(region)
        .filterDate(start_date, end_date)
        .filter(ee.Filter.eq("instrumentMode", "IW"))
        .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
        .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VH"))
        .filter(ee.Filter.eq("orbitProperties_pass", "DESCENDING"))
        .select(["VV", "VH"])
    )

    count = collection.size().getInfo()
    print(f"[GEE]   → {count} scene(s) found")

    if count == 0:
        raise RuntimeError(
            f"No Sentinel-1 scenes found for {label} "
            f"({start_date} → {end_date}) in the given region. "
            "Try expanding the date range or switching to ASCENDING orbit."
        )

    # Apply speckle filter to each scene, then take median composite
    filtered = collection.map(apply_speckle_filter)
    composite = filtered.median().clip(region)

    print(f"[GEE]   → Speckle-filtered median composite ready")
    return composite


def get_srtm_dem(region) -> object:
    """Return the SRTM 30m DEM clipped to the given region.

    Uses the ``USGS/SRTMGL1_003`` dataset (30m horizontal resolution).

    Parameters
    ----------
    region : ee.Geometry
        Area of interest.

    Returns
    -------
    ee.Image
        Single-band ``elevation`` image (metres, Int16).
    """
    import ee  # type: ignore[import]

    print("[GEE] Loading SRTM DEM (USGS/SRTMGL1_003) …")
    dem = ee.Image("USGS/SRTMGL1_003").select("elevation").clip(region)
    print("[GEE]   → DEM ready")
    return dem


# ---------------------------------------------------------------------------
# Download helpers
# ---------------------------------------------------------------------------

def _download_band(
    image,
    band: str,
    region,
    scale: int,
    output_path: Path,
) -> None:
    """Download a single band from a GEE image as a GeoTIFF.

    Uses ``ee.Image.getDownloadURL()`` with format ``GEO_TIFF``.
    The downloaded file is written directly to ``output_path``.

    Parameters
    ----------
    image : ee.Image
        Source image (will be ``.select([band])`` before download).
    band : str
        Band name to download (e.g. ``"VV"``, ``"elevation"``).
    region : ee.Geometry
        Spatial extent.
    scale : int
        Pixel resolution in metres.
    output_path : Path
        Local file path to write the GeoTIFF to (parent must exist).

    Raises
    ------
    requests.HTTPError
        If the GEE download URL returns a non-200 status.
    RuntimeError
        If GEE returns a zip instead of a plain GeoTIFF (unexpected format).
    """
    import ee  # type: ignore[import]

    print(f"[DL]   Getting download URL for band '{band}' at {scale}m …")

    url = image.select([band]).getDownloadURL(
        {
            "region":     region,
            "scale":      scale,
            "format":     "GEO_TIFF",
            "crs":        "EPSG:4326",
        }
    )

    print(f"[DL]   Downloading → {output_path.name} …", end="", flush=True)
    resp = requests.get(url, stream=True, timeout=300)
    resp.raise_for_status()

    content_type = resp.headers.get("Content-Type", "")
    raw = b"".join(resp.iter_content(chunk_size=8192))

    # GEE may return a zip for multi-band or single-band (handle both)
    if "zip" in content_type or raw[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            tif_names = [n for n in zf.namelist() if n.endswith(".tif")]
            if not tif_names:
                raise RuntimeError(f"No .tif file in GEE zip for band '{band}'")
            raw = zf.read(tif_names[0])

    output_path.write_bytes(raw)
    size_mb = len(raw) / (1024 ** 2)
    print(f" {size_mb:.1f} MB ✓")


def stack_bands(
    band_paths: list[Path],
    output_path: Path,
    band_names: list[str],
) -> None:
    """Stack multiple single-band GeoTIFFs into one multi-band GeoTIFF.

    Parameters
    ----------
    band_paths : list[Path]
        Ordered list of single-band GeoTIFF paths.
    output_path : Path
        Destination path for the stacked multi-band GeoTIFF.
    band_names : list[str]
        Band descriptions (same order as ``band_paths``).
    """
    print(f"[IO]   Stacking {len(band_paths)} bands → {output_path.name} …", end="")

    arrays = []
    with rasterio.open(band_paths[0]) as src:
        meta = src.meta.copy()
        arrays.append(src.read(1))

    for p in band_paths[1:]:
        with rasterio.open(p) as src:
            arrays.append(src.read(1))

    meta.update(count=len(arrays), dtype="float32")

    with rasterio.open(output_path, "w", **meta) as dst:
        for i, (arr, name) in enumerate(zip(arrays, band_names), start=1):
            dst.write(arr.astype(np.float32), i)
            dst.update_tags(i, name=name)

    print(" ✓")

    # Remove intermediary single-band files
    for p in band_paths:
        p.unlink(missing_ok=True)


def download_composite(
    image,
    region,
    scale: int,
    bands: list[str],
    output_path: Path,
) -> None:
    """Download a multi-band composite as a stacked GeoTIFF.

    Downloads each band separately (to stay within GEE size limits), then
    merges them into a single multi-band GeoTIFF using ``stack_bands()``.

    Parameters
    ----------
    image : ee.Image
        Source composite image.
    region : ee.Geometry
        Spatial extent.
    scale : int
        Pixel resolution in metres.
    bands : list[str]
        Band names to download and stack.
    output_path : Path
        Final stacked GeoTIFF path.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_paths = []

    for band in bands:
        tmp = output_path.parent / f"_tmp_{band}_{output_path.stem}.tif"
        _download_band(image, band, region, scale, tmp)
        tmp_paths.append(tmp)

    stack_bands(tmp_paths, output_path, bands)


# ---------------------------------------------------------------------------
# Drive export (production alternative for large areas / 10m scale)
# ---------------------------------------------------------------------------

def export_to_drive(
    image,
    description: str,
    folder: str,
    region,
    scale: int = 10,
) -> None:
    """Export a GEE image to Google Drive (async, large-area safe).

    This is the production alternative to ``download_composite()`` when
    ``scale=10`` or when ``getDownloadURL`` hits the size limit.

    After calling this function, log in to https://drive.google.com and
    download the exported GeoTIFF manually (or use the Drive API).

    Parameters
    ----------
    image : ee.Image
        Image to export.
    description : str
        Task name visible in GEE task manager.
    folder : str
        Google Drive folder name (created if absent).
    region : ee.Geometry
        Export region.
    scale : int
        Pixel resolution in metres. Default 10m.
    """
    import ee  # type: ignore[import]

    task = ee.batch.Export.image.toDrive(
        image=image,
        description=description,
        folder=folder,
        region=region,
        scale=scale,
        crs="EPSG:4326",
        maxPixels=1e13,
        fileFormat="GeoTIFF",
    )
    task.start()
    print(f"[GEE] Drive export started: '{description}'")
    print(f"      Monitor at: https://code.earthengine.google.com/tasks")
    print(f"      Check status: task.status()['state']")

    # Poll until done (blocks — comment out for fire-and-forget)
    print("[GEE] Waiting for export … (Ctrl-C to run in background)", end="")
    while True:
        state = task.status()["state"]
        if state == "COMPLETED":
            print(" ✓")
            break
        elif state in ("FAILED", "CANCELLED"):
            raise RuntimeError(f"GEE Drive export failed: {task.status()}")
        print(".", end="", flush=True)
        time.sleep(15)


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------

def pull_all(output_dir: Path, scale: int = 60) -> None:
    """Download all required datasets for the Kerala 2018 flood analysis.

    Datasets downloaded:
    - ``s1_pre_flood.tif``    Sentinel-1 VV+VH, June 2018
    - ``s1_during_flood.tif`` Sentinel-1 VV+VH, August 2018
    - ``srtm_dem.tif``        SRTM elevation, 30m

    Parameters
    ----------
    output_dir : Path
        Local directory to write GeoTIFFs to (created if absent).
    scale : int
        Pixel resolution in metres for Sentinel-1 downloads.
        Use 60 for quick tests; 30 for full-resolution inference.
        SRTM is always downloaded at 30m (native resolution).
    """
    import ee  # type: ignore[import]

    authenticate_gee()

    print(f"\n[INFO] Output directory : {output_dir}")
    print(f"[INFO] Download scale   : {scale}m\n")
    output_dir.mkdir(parents=True, exist_ok=True)

    region = bbox_to_ee_region(KERALA_BBOX)

    # ------------------------------------------------------------------ #
    # 1. Pre-flood composite (June 2018)                                  #
    # ------------------------------------------------------------------ #
    pre_out = output_dir / "s1_pre_flood.tif"
    if pre_out.exists():
        print(f"[SKIP] {pre_out.name} already exists — delete to re-download")
    else:
        pre_composite = get_sentinel1_composite(
            region,
            PRE_FLOOD_START,
            PRE_FLOOD_END,
            label="Pre-flood (June 2018)",
        )
        download_composite(
            image=pre_composite,
            region=region,
            scale=scale,
            bands=["VV", "VH"],
            output_path=pre_out,
        )

    # ------------------------------------------------------------------ #
    # 2. During-flood composite (August 2018)                             #
    # ------------------------------------------------------------------ #
    during_out = output_dir / "s1_during_flood.tif"
    if during_out.exists():
        print(f"[SKIP] {during_out.name} already exists — delete to re-download")
    else:
        during_composite = get_sentinel1_composite(
            region,
            DURING_FLOOD_START,
            DURING_FLOOD_END,
            label="During-flood (August 2018)",
        )
        download_composite(
            image=during_composite,
            region=region,
            scale=scale,
            bands=["VV", "VH"],
            output_path=during_out,
        )

    # ------------------------------------------------------------------ #
    # 3. SRTM DEM (always 30m native resolution)                         #
    # ------------------------------------------------------------------ #
    dem_out = output_dir / "srtm_dem.tif"
    if dem_out.exists():
        print(f"[SKIP] {dem_out.name} already exists — delete to re-download")
    else:
        dem = get_srtm_dem(region)
        _download_band(dem, "elevation", region, scale=30, output_path=dem_out)

    # ------------------------------------------------------------------ #
    # Summary                                                             #
    # ------------------------------------------------------------------ #
    print("\n" + "=" * 60)
    print("  Download complete. Files:")
    for fname in ["s1_pre_flood.tif", "s1_during_flood.tif", "srtm_dem.tif"]:
        fpath = output_dir / fname
        if fpath.exists():
            mb = fpath.stat().st_size / (1024 ** 2)
            print(f"    {fname:<26}  {mb:6.1f} MB")
    print("=" * 60)
    print("\nNext step:")
    print("  python ml/inference/flood_inference.py")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Download Sentinel-1 + SRTM data for OrbitalMind Kerala flood demo"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=_DEFAULT_OUT,
        help=f"Output directory (default: {_DEFAULT_OUT})",
    )
    parser.add_argument(
        "--scale",
        type=int,
        default=60,
        help="Download resolution in metres (default: 60; use 30 for full-res)",
    )
    args = parser.parse_args()
    pull_all(output_dir=args.output, scale=args.scale)
