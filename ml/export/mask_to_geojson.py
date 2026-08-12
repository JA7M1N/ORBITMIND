"""
OrbitalMind — GeoTIFF Flood Mask → GeoJSON Exporter
=====================================================
Converts the binary ``flood_mask.tif`` and ``confidence_map.tif`` produced
by the Attention U-Net pipeline into three web-ready geospatial files:

Output files (written to backend/demo_data/flood/kerala_2018/)
--------------------------------------------------------------
  flood_mask.geojson          GeoJSON FeatureCollection of flood polygons
  confidence_contours.geojson GeoJSON polygons at confidence thresholds
  flood_stats.json            Scene-level summary statistics

Pipeline
--------
1. Load flood_mask.tif (uint8) and confidence_map.tif (float32) via rasterio
2. Vectorise connected flood regions with rasterio.features.shapes()
3. Simplify each polygon geometry (shapely, tolerance=0.0001°)
4. Compute per-polygon confidence from the confidence map (mean within bbox)
5. Compute area_km2 from polygon extent
6. Write flood_mask.geojson with all properties
7. Generate confidence_contours.geojson at levels [0.5, 0.6, 0.7, 0.8, 0.9]
8. Write flood_stats.json with aggregate statistics

Usage
-----
    # From OrbitalMind root:
    python ml/export/mask_to_geojson.py

    # Custom paths:
    python ml/export/mask_to_geojson.py \\
        --mask       data/kerala_2018/flood_mask.tif \\
        --confidence data/kerala_2018/confidence_map.tif \\
        --output     backend/demo_data/flood/kerala_2018
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Optional

import numpy as np
import rasterio
from rasterio.features import shapes as rasterio_shapes
from shapely.geometry import shape as shapely_shape, mapping as shapely_mapping

# ---------------------------------------------------------------------------
# Repo-relative default paths
# ---------------------------------------------------------------------------
_REPO_ROOT     = Path(__file__).resolve().parents[3]   # OrbitalMind/
_MASK_PATH     = _REPO_ROOT / "data" / "kerala_2018" / "flood_mask.tif"
_CONF_PATH     = _REPO_ROOT / "data" / "kerala_2018" / "confidence_map.tif"
_OUTPUT_DIR    = _REPO_ROOT / "backend" / "demo_data" / "flood" / "kerala_2018"

# Geometry simplification tolerance in degrees (~10m at this latitude)
SIMPLIFY_TOLERANCE = 0.0001

# Confidence contour levels (lower bound of each band)
CONTOUR_LEVELS = [0.5, 0.6, 0.7, 0.8, 0.9]

# Minimum flood polygon area to keep (noise filter)
MIN_AREA_KM2 = 0.005


# ---------------------------------------------------------------------------
# Core: vectorise flood mask
# ---------------------------------------------------------------------------

def vectorise_mask(
    mask_path:       Path,
    confidence_path: Path,
    min_area_km2:    float = MIN_AREA_KM2,
) -> tuple[list[dict], np.ndarray, dict]:
    """Vectorise a binary flood mask GeoTIFF into GeoJSON features.

    For each connected flood region (value=1 in the mask), this function:
    - Extracts the polygon boundary using ``rasterio.features.shapes``
    - Simplifies the geometry with Shapely (tolerance = 0.0001°)
    - Computes the mean confidence from the overlapping region of the
      confidence map
    - Estimates the area in km²

    Parameters
    ----------
    mask_path : Path
        Binary flood mask GeoTIFF (uint8, 1=flood, 0=dry).
    confidence_path : Path
        Float32 confidence map GeoTIFF (sigmoid probabilities 0–1).
    min_area_km2 : float
        Polygons smaller than this are discarded as noise.

    Returns
    -------
    features : list[dict]
        List of GeoJSON Feature dicts with geometry and properties.
    conf_array : np.ndarray
        Raw confidence map array (H, W) float32 — used for contour generation.
    sar_meta : dict
        Rasterio metadata from the mask file.

    Raises
    ------
    FileNotFoundError
        If either GeoTIFF is not found.
    """
    if not mask_path.exists():
        raise FileNotFoundError(
            f"Flood mask not found: {mask_path}\n"
            "Run the inference pipeline first: python ml/inference/flood_inference.py"
        )
    if not confidence_path.exists():
        raise FileNotFoundError(
            f"Confidence map not found: {confidence_path}\n"
            "Run the inference pipeline first: python ml/inference/flood_inference.py"
        )

    # ------------------------------------------------------------------
    # Load rasters
    # ------------------------------------------------------------------
    print(f"[LOAD] flood_mask.tif      : {mask_path}")
    with rasterio.open(mask_path) as src:
        mask_arr  = src.read(1).astype(np.uint8)
        sar_meta  = src.meta.copy()
        transform = src.transform
        H, W      = mask_arr.shape

    print(f"[LOAD] confidence_map.tif  : {confidence_path}")
    with rasterio.open(confidence_path) as src:
        conf_arr = src.read(1).astype(np.float32)

    # Resize confidence map to match mask if shapes differ (edge case)
    if conf_arr.shape != mask_arr.shape:
        from scipy.ndimage import zoom as ndimage_zoom
        scale_h = H / conf_arr.shape[0]
        scale_w = W / conf_arr.shape[1]
        conf_arr = ndimage_zoom(conf_arr, (scale_h, scale_w), order=1)
        print(f"[WARN] Confidence map resized to match mask shape {(H, W)}")

    # Pixel area in km² (approximate using degree → km conversion)
    px_deg_lon = abs(transform.a)   # degrees per pixel (longitude)
    px_deg_lat = abs(transform.e)   # degrees per pixel (latitude)
    # At ~10°N latitude: 1° lon ≈ 109.9 km, 1° lat ≈ 111.0 km
    cx_lat     = sar_meta.get("transform", transform).f - (H / 2) * abs(transform.e)
    km_per_deg_lon = 111.0 * np.cos(np.radians(abs(cx_lat)))
    km_per_deg_lat = 111.0
    pixel_km2  = (px_deg_lon * km_per_deg_lon) * (px_deg_lat * km_per_deg_lat)

    print(f"[INFO] Image: {W}×{H}px, pixel area ≈ {pixel_km2*1e6:.0f} m²")
    print(f"[VEC]  Vectorising {int(mask_arr.sum()):,} flooded pixels …")

    # ------------------------------------------------------------------
    # Vectorise with rasterio.features.shapes
    # ------------------------------------------------------------------
    features   = []
    n_raw      = 0
    n_filtered = 0

    for geom_dict, val in rasterio_shapes(mask_arr, transform=transform):
        if val != 1:
            continue
        n_raw += 1

        # Convert to Shapely for simplification and area calculation
        poly = shapely_shape(geom_dict)

        # Area in km² (rough: pixel count × pixel_km2)
        # Use bounds-based approach for speed (exact area via projected CRS
        # would require pyproj — keep dependencies minimal)
        bounds   = poly.bounds   # (min_lon, min_lat, max_lon, max_lat)
        width_km = (bounds[2] - bounds[0]) * km_per_deg_lon
        height_km= (bounds[3] - bounds[1]) * km_per_deg_lat
        area_km2 = width_km * height_km * 0.5   # rough polygon fill factor

        if area_km2 < min_area_km2:
            n_filtered += 1
            continue

        # Simplify geometry for web rendering
        simplified = poly.simplify(SIMPLIFY_TOLERANCE, preserve_topology=True)
        if not simplified.is_valid or simplified.is_empty:
            n_filtered += 1
            continue

        # Mean confidence within polygon bounding box
        r0 = max(0, int((transform.f - bounds[3]) / abs(transform.e)))
        c0 = max(0, int((bounds[0]  - transform.c) / transform.a))
        r1 = min(H, r0 + max(1, int(height_km / (px_deg_lat * km_per_deg_lat))))
        c1 = min(W, c0 + max(1, int(width_km  / (px_deg_lon * km_per_deg_lon))))

        region_conf = conf_arr[r0:r1, c0:c1]
        flood_confs = region_conf[region_conf > 0.5]
        mean_conf   = float(flood_confs.mean()) if len(flood_confs) > 0 else 0.0

        features.append(
            {
                "type":     "Feature",
                "geometry": shapely_mapping(simplified),
                "properties": {
                    "confidence":    round(mean_conf, 4),
                    "area_km2":      round(area_km2, 4),
                    "disaster_type": "flood",
                    "source":        "unet_inference",
                    "event_id":      "kerala_2018",
                },
            }
        )

    print(
        f"[VEC]  Shapes extracted: {n_raw}  |  after area filter: {len(features)}  "
        f"(removed {n_filtered} small/invalid)"
    )
    return features, conf_arr, sar_meta


# ---------------------------------------------------------------------------
# Confidence contours
# ---------------------------------------------------------------------------

def generate_confidence_contours(
    conf_array: np.ndarray,
    sar_meta:   dict,
    levels:     list[float] = CONTOUR_LEVELS,
) -> list[dict]:
    """Generate confidence band polygons as a GeoJSON FeatureCollection.

    For each consecutive pair of levels (lo, hi), vectorises the region where
    ``lo ≤ confidence < hi`` as a filled polygon band.  These can be rendered
    as a choropleth overlay showing model certainty.

    Parameters
    ----------
    conf_array : np.ndarray
        Shape ``(H, W)`` float32 confidence map.
    sar_meta : dict
        Rasterio metadata (for transform).
    levels : list[float]
        Confidence thresholds.  E.g. ``[0.5, 0.6, 0.7, 0.8, 0.9]``.
        Produces ``len(levels)`` contour bands (last band: level → 1.0).

    Returns
    -------
    list[dict]
        GeoJSON Feature list for each contour band.
    """
    transform  = sar_meta["transform"]
    features   = []
    H, W       = conf_array.shape
    all_levels = levels + [1.01]   # sentinel to cap the last band

    for i, (lo, hi) in enumerate(zip(all_levels[:-1], all_levels[1:])):
        band_mask = ((conf_array >= lo) & (conf_array < hi)).astype(np.uint8)
        if band_mask.sum() == 0:
            continue

        for geom_dict, val in rasterio_shapes(band_mask, transform=transform):
            if val != 1:
                continue
            poly = shapely_shape(geom_dict)
            if poly.area < 1e-8:
                continue
            simplified = poly.simplify(SIMPLIFY_TOLERANCE, preserve_topology=True)
            if not simplified.is_valid or simplified.is_empty:
                continue

            features.append(
                {
                    "type":     "Feature",
                    "geometry": shapely_mapping(simplified),
                    "properties": {
                        "confidence_lo": lo,
                        "confidence_hi": min(hi, 1.0),
                        "confidence_mid": round((lo + min(hi, 1.0)) / 2, 2),
                        "band_label":    f"{lo:.0%}–{min(hi,1.0):.0%}",
                        "disaster_type": "flood",
                    },
                }
            )

    print(f"[CONT] Generated {len(features)} confidence contour polygon(s)")
    return features


# ---------------------------------------------------------------------------
# Flood stats
# ---------------------------------------------------------------------------

def compute_flood_stats(
    features:   list[dict],
    conf_array: np.ndarray,
    sar_meta:   dict,
) -> dict:
    """Compute aggregate scene-level flood statistics.

    Parameters
    ----------
    features : list[dict]
        GeoJSON Features from ``vectorise_mask()``.
    conf_array : np.ndarray
        Confidence map array.
    sar_meta : dict
        Rasterio metadata.

    Returns
    -------
    dict
        Statistics dict suitable for saving as ``flood_stats.json``.
    """
    transform = sar_meta["transform"]
    bbox = [
        transform.c,
        transform.f + sar_meta["height"] * transform.e,
        transform.c + sar_meta["width"]  * transform.a,
        transform.f,
    ]  # [west, south, east, north]

    total_area   = sum(f["properties"]["area_km2"] for f in features)
    confidences  = [f["properties"]["confidence"] for f in features]
    avg_conf     = float(np.mean(confidences)) if confidences else 0.0
    peak_conf    = float(np.max(confidences))  if confidences else 0.0
    finite_confs = conf_array[np.isfinite(conf_array) & (conf_array > 0)]

    return {
        "event_id":         "kerala_2018",
        "disaster_type":    "flood",
        "total_area_km2":   round(total_area, 2),
        "avg_confidence":   round(avg_conf, 4),
        "peak_confidence":  round(peak_conf, 4),
        "scene_mean_conf":  round(float(finite_confs.mean()) if len(finite_confs) > 0 else 0.0, 4),
        "feature_count":    len(features),
        "image_width_px":   sar_meta["width"],
        "image_height_px":  sar_meta["height"],
        "bbox":             [round(v, 6) for v in bbox],
        "crs":              str(sar_meta.get("crs", "EPSG:4326")),
        "simplify_tolerance": SIMPLIFY_TOLERANCE,
    }


# ---------------------------------------------------------------------------
# Write outputs
# ---------------------------------------------------------------------------

def export_all(
    mask_path:       Path,
    confidence_path: Path,
    output_dir:      Path,
) -> dict:
    """Run the complete export pipeline and write all three output files.

    Parameters
    ----------
    mask_path : Path
        Binary flood mask GeoTIFF.
    confidence_path : Path
        Float32 confidence map GeoTIFF.
    output_dir : Path
        Destination directory (created if absent).

    Returns
    -------
    dict
        The ``flood_stats.json`` contents dict.
    """
    t0 = time.perf_counter()
    output_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # 1. Vectorise flood mask
    # ------------------------------------------------------------------
    features, conf_array, sar_meta = vectorise_mask(mask_path, confidence_path)

    # ------------------------------------------------------------------
    # 2. Write flood_mask.geojson
    # ------------------------------------------------------------------
    flood_geojson = {
        "type":     "FeatureCollection",
        "features": features,
    }
    mask_out = output_dir / "flood_mask.geojson"
    with mask_out.open("w", encoding="utf-8") as fh:
        json.dump(flood_geojson, fh, indent=2)
    print(f"[IO]   Written: {mask_out.name}  ({len(features)} features)")

    # ------------------------------------------------------------------
    # 3. Confidence contours
    # ------------------------------------------------------------------
    contour_features = generate_confidence_contours(conf_array, sar_meta)
    contour_geojson  = {
        "type":     "FeatureCollection",
        "features": contour_features,
    }
    contour_out = output_dir / "confidence_contours.geojson"
    with contour_out.open("w", encoding="utf-8") as fh:
        json.dump(contour_geojson, fh, indent=2)
    print(f"[IO]   Written: {contour_out.name}  ({len(contour_features)} contour bands)")

    # ------------------------------------------------------------------
    # 4. Flood stats
    # ------------------------------------------------------------------
    stats     = compute_flood_stats(features, conf_array, sar_meta)
    stats_out = output_dir / "flood_stats.json"
    with stats_out.open("w", encoding="utf-8") as fh:
        json.dump(stats, fh, indent=2)
    print(f"[IO]   Written: {stats_out.name}")

    elapsed = time.perf_counter() - t0
    print(f"\n{'='*55}")
    print(f"  Export complete  ({elapsed:.1f}s)")
    print(f"{'='*55}")
    print(f"  Total flooded area : {stats['total_area_km2']} km²")
    print(f"  Average confidence : {stats['avg_confidence']}")
    print(f"  Feature count      : {stats['feature_count']}")
    print(f"  Output dir         : {output_dir}")
    print(f"{'='*55}\n")

    return stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Convert flood GeoTIFFs to web-ready GeoJSON + stats"
    )
    parser.add_argument("--mask",       type=Path, default=_MASK_PATH,  help="Flood mask GeoTIFF")
    parser.add_argument("--confidence", type=Path, default=_CONF_PATH,  help="Confidence map GeoTIFF")
    parser.add_argument("--output",     type=Path, default=_OUTPUT_DIR, help="Output directory")
    args = parser.parse_args()
    export_all(args.mask, args.confidence, args.output)
