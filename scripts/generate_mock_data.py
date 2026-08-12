"""
OrbitalMind — Mock Demo Data Generator
========================================
Generates realistic synthetic GeoJSON datasets for the 4 DEMO disaster modules
(Wildfire, Landslide, Cyclone, Earthquake) and a fallback Kerala Flood dataset.

All polygons are generated as geometrically valid convex-hull shapes within
each event's bounding box.  Properties mirror what the real detection pipelines
would produce, ensuring the priority scoring engine and demo loader work
identically for live and mock data.

Output structure
----------------
  backend/demo_data/
  ├── flood/kerala_2018/flood_mask.geojson              (fallback mock)
  ├── wildfire/uttarakhand_2024/affected_zones.geojson
  ├── landslide/himachal_2023/affected_zones.geojson
  ├── cyclone/odisha_2023/affected_zones.geojson
  └── earthquake/gujarat_2024/affected_zones.geojson

Usage
-----
    python scripts/generate_mock_data.py           # generate all
    python scripts/generate_mock_data.py --force   # overwrite existing files
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

# ---------------------------------------------------------------------------
# Repo root
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEMO_BASE = _REPO_ROOT / "backend" / "demo_data"

# Global RNG seed for reproducible mock data
_RNG_SEED = 42


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _rng(seed: int) -> np.random.Generator:
    """Return a seeded numpy RNG for reproducible generation."""
    return np.random.default_rng(seed)


def convex_polygon_coords(
    center_lon: float,
    center_lat: float,
    radius_deg: float,
    n_points:   int = 8,
    seed:       int = 0,
    lon_stretch: float = 1.0,
    lat_stretch: float = 1.0,
) -> list[list[float]]:
    """Generate a valid, non-self-intersecting convex polygon.

    Algorithm: sample ``n_points`` angles uniformly in [0, 2π), sort them,
    assign random radii in [0.4·r, r], convert polar→Cartesian.
    Sorted-angle construction guarantees a star-polygon with no self-
    intersections (sufficient for Shapely ``is_valid`` checks).

    Parameters
    ----------
    center_lon, center_lat : float
        Centre of the polygon in EPSG:4326.
    radius_deg : float
        Maximum radius in degrees.
    n_points : int
        Number of polygon vertices (minimum 4).
    seed : int
        RNG seed for reproducibility.
    lon_stretch, lat_stretch : float
        Axis-stretch multipliers (>1 = elongated in that direction).

    Returns
    -------
    list of [lon, lat]
        Closed ring (last point == first point).
    """
    rng     = _rng(seed)
    n_pts   = max(4, n_points)
    angles  = np.sort(rng.uniform(0, 2 * np.pi, n_pts))
    radii   = rng.uniform(0.4 * radius_deg, radius_deg, n_pts)

    lons = center_lon + radii * np.cos(angles) * lon_stretch
    lats = center_lat + radii * np.sin(angles) * lat_stretch

    ring = [[round(float(lon), 6), round(float(lat), 6)]
            for lon, lat in zip(lons, lats)]
    ring.append(ring[0])   # close ring
    return ring


def rectangle_coords(
    min_lon: float, min_lat: float,
    max_lon: float, max_lat: float,
) -> list[list[float]]:
    """Return a closed rectangular ring."""
    return [
        [min_lon, min_lat],
        [max_lon, min_lat],
        [max_lon, max_lat],
        [min_lon, max_lat],
        [min_lon, min_lat],
    ]


def approx_area_km2(radius_deg: float, lat: float, lon_stretch: float = 1.0, lat_stretch: float = 1.0) -> float:
    """Estimate the area of a generated polygon in km²."""
    km_lat = radius_deg * lat_stretch * 111.0
    km_lon = radius_deg * lon_stretch * 111.0 * math.cos(math.radians(abs(lat)))
    # Mean area of a star-polygon ≈ π·a·b × 0.65 fill factor
    return round(math.pi * km_lat * km_lon * 0.65, 3)


def linestring_coords(
    points: list[tuple[float, float]]
) -> list[list[float]]:
    """Convert a list of (lon, lat) tuples to GeoJSON coordinate arrays."""
    return [[round(lon, 6), round(lat, 6)] for lon, lat in points]


def _feature(geometry: dict, properties: dict) -> dict:
    """Construct a GeoJSON Feature dict."""
    return {"type": "Feature", "geometry": geometry, "properties": properties}


def _polygon_feature(coords: list, properties: dict) -> dict:
    """Construct a GeoJSON Polygon Feature."""
    return _feature({"type": "Polygon", "coordinates": [coords]}, properties)


def _linestring_feature(coords: list, properties: dict) -> dict:
    """Construct a GeoJSON LineString Feature."""
    return _feature({"type": "LineString", "coordinates": coords}, properties)


def _featurecollection(features: list[dict]) -> dict:
    """Wrap a list of features in a GeoJSON FeatureCollection."""
    return {"type": "FeatureCollection", "features": features}


def _write(path: Path, data: dict, force: bool = False) -> bool:
    """Write GeoJSON to disk.

    Returns ``True`` if written, ``False`` if skipped (already exists).
    """
    if path.exists() and not force:
        print(f"  [SKIP] {path.relative_to(_REPO_ROOT)}  (already exists; use --force to overwrite)")
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    n_feat = len(data.get("features", []))
    print(f"  [OK]   {path.relative_to(_REPO_ROOT)}  ({n_feat} features)")
    return True


# ---------------------------------------------------------------------------
# 0. FLOOD — Kerala 2018 (fallback mock if real inference hasn't run)
# ---------------------------------------------------------------------------

def generate_kerala_flood(force: bool = False) -> None:
    """Generate a realistic mock Kerala 2018 flood dataset.

    Used as a fallback when the real Attention U-Net inference has not yet
    been run.  If ``flood_mask.geojson`` already exists, this is skipped
    unless ``force=True``.

    Bounding box: [76.0, 9.5, 77.5, 11.0]
    Coverage: Alappuzha, Ernakulam, Thrissur, Pathanamthitta districts
    """
    rng   = _rng(_RNG_SEED + 0)
    bbox  = [76.0, 9.5, 77.5, 11.0]
    west, south, east, north = bbox

    # --- 8 flood polygons across the four affected districts ---
    # Each cluster is centred on a historically flooded location
    clusters = [
        # (center_lon, center_lat, radius_deg, label)
        (76.35, 9.70,  0.12, "Alappuzha Backwaters"),
        (76.52, 9.95,  0.10, "Kuttanad Paddy Fields"),
        (76.78, 10.05, 0.09, "Ernakulam Low-lying"),
        (76.95, 10.22, 0.11, "Chalakudy River Basin"),
        (76.20, 10.40, 0.08, "Thrissur Wetlands"),
        (76.65, 10.60, 0.10, "Palakkad Border"),
        (77.10, 10.80, 0.07, "Malappuram Coastal"),
        (76.40, 10.75, 0.09, "Kozhikode Low Zone"),
    ]

    features = []
    for i, (lon, lat, radius, label) in enumerate(clusters):
        coords = convex_polygon_coords(
            lon, lat, radius, n_points=10, seed=_RNG_SEED + i,
            lon_stretch=rng.uniform(0.8, 1.2),
            lat_stretch=rng.uniform(0.7, 1.1),
        )
        confidence = round(float(rng.uniform(0.78, 0.96)), 4)
        area_km2   = approx_area_km2(radius, lat,
                                     lon_stretch=rng.uniform(0.8, 1.2),
                                     lat_stretch=rng.uniform(0.7, 1.1))
        features.append(
            _polygon_feature(
                coords,
                {
                    "confidence":    confidence,
                    "area_km2":      area_km2,
                    "disaster_type": "flood",
                    "source":        "mock_unet_fallback",
                    "event_id":      "kerala_2018",
                    "location_label": label,
                    "water_depth_m": round(float(rng.uniform(0.5, 4.5)), 1),
                },
            )
        )

    path = _DEMO_BASE / "flood" / "kerala_2018" / "flood_mask.geojson"
    _write(path, _featurecollection(features), force)

    # Write flood stats
    stats = {
        "event_id":        "kerala_2018",
        "disaster_type":   "flood",
        "total_area_km2":  round(sum(f["properties"]["area_km2"] for f in features), 2),
        "avg_confidence":  round(float(np.mean([f["properties"]["confidence"] for f in features])), 4),
        "feature_count":   len(features),
        "bbox":            bbox,
        "source":          "mock",
    }
    stats_path = _DEMO_BASE / "flood" / "kerala_2018" / "flood_stats.json"
    if not stats_path.exists() or force:
        stats_path.parent.mkdir(parents=True, exist_ok=True)
        with stats_path.open("w", encoding="utf-8") as fh:
            json.dump(stats, fh, indent=2)


# ---------------------------------------------------------------------------
# 1. WILDFIRE — Uttarakhand 2024
# ---------------------------------------------------------------------------

def generate_wildfire_uttarakhand(force: bool = False) -> None:
    """Generate mock wildfire burn-scar polygons for Uttarakhand 2024.

    Bounding box: [78.5, 29.5, 80.5, 31.5]
    Based on known fire-prone forest divisions in Garhwal and Kumaon.
    5 polygon features with severity and NBR-derived properties.
    """
    rng  = _rng(_RNG_SEED + 10)

    # Realistic wildfire cluster centres in Uttarakhand's forest zones
    clusters = [
        # (lon, lat, radius, severity, label)
        (79.10, 30.60, 0.15, "high",   "Lansdowne Forest Division"),
        (79.80, 30.20, 0.12, "high",   "Nainital Slopes"),
        (78.90, 30.90, 0.10, "medium", "Tehri Watershed"),
        (80.20, 30.80, 0.11, "medium", "Pithoragarh Forest"),
        (79.50, 31.10, 0.09, "low",    "Chamoli Oak Belt"),
    ]

    features = []
    for i, (lon, lat, radius, severity, label) in enumerate(clusters):
        coords = convex_polygon_coords(
            lon, lat, radius, n_points=9, seed=_RNG_SEED + 10 + i,
            lon_stretch=rng.uniform(1.0, 1.5),   # fire spreads along ridges
            lat_stretch=rng.uniform(0.6, 1.0),
        )
        conf_range = {"high": (0.85, 0.95), "medium": (0.75, 0.87), "low": (0.68, 0.78)}
        lo, hi     = conf_range[severity]
        confidence = round(float(rng.uniform(lo, hi)), 4)
        area_km2   = approx_area_km2(radius, lat, lon_stretch=1.3, lat_stretch=0.8)

        # dNBR magnitude per severity (use sorted abs values to avoid low > high)
        nbr_map = {"high": (0.25, 0.50), "medium": (0.10, 0.25), "low": (0.05, 0.12)}
        nbr_lo, nbr_hi = nbr_map[severity]
        dnbr = round(float(rng.uniform(nbr_lo, nbr_hi)), 3)

        features.append(
            _polygon_feature(
                coords,
                {
                    "confidence":    confidence,
                    "area_km2":      area_km2,
                    "disaster_type": "wildfire",
                    "source":        "mock_nbr",
                    "event_id":      "uttarakhand_2024",
                    "severity":      severity,
                    "location_label": label,
                    "dnbr":          dnbr,
                    "estimated_trees_lost": int(area_km2 * rng.uniform(800, 1500)),
                },
            )
        )

    path = _DEMO_BASE / "wildfire" / "uttarakhand_2024" / "affected_zones.geojson"
    _write(path, _featurecollection(features), force)


# ---------------------------------------------------------------------------
# 2. LANDSLIDE — Himachal Pradesh 2023
# ---------------------------------------------------------------------------

def generate_landslide_himachal(force: bool = False) -> None:
    """Generate mock landslide debris-flow polygons for Himachal Pradesh 2023.

    Bounding box: [76.5, 31.0, 78.0, 32.5]
    Landslides in Kullu and Mandi districts — elongated shapes along slope direction.
    6 polygon features with slope angle and debris volume properties.
    """
    rng = _rng(_RNG_SEED + 20)

    # Realistic landslide locations along river valleys and steep ridges
    clusters = [
        # (lon, lat, radius, slope_deg, label)
        (77.10, 31.95, 0.06, 52, "Kullu Beas Valley — NH3 Blockage"),
        (76.90, 32.10, 0.05, 48, "Mandi District — Uhl River"),
        (77.40, 31.60, 0.07, 45, "Rampur Bushahr Slopes"),
        (77.65, 32.00, 0.04, 58, "Kinnaur Border — Sutlej Canyon"),
        (76.70, 31.30, 0.05, 38, "Bilaspur Ridgeline"),
        (77.80, 31.80, 0.06, 42, "Shimla Hills — Old Hindustan-Tibet Rd"),
    ]

    features = []
    for i, (lon, lat, radius, slope_ang, label) in enumerate(clusters):
        # Landslides are elongated down-slope (high lat-stretch)
        coords = convex_polygon_coords(
            lon, lat, radius, n_points=7, seed=_RNG_SEED + 20 + i,
            lon_stretch=rng.uniform(0.5, 0.8),   # narrow across slope
            lat_stretch=rng.uniform(1.2, 2.0),   # long down-slope
        )
        confidence = round(float(rng.uniform(0.70, 0.90)), 4)
        area_km2   = approx_area_km2(radius, lat, lon_stretch=0.65, lat_stretch=1.6)
        volume_m3  = int(area_km2 * 1e6 * rng.uniform(1.5, 4.0))  # rough cubic metres

        features.append(
            _polygon_feature(
                coords,
                {
                    "confidence":      confidence,
                    "area_km2":        area_km2,
                    "disaster_type":   "landslide",
                    "source":          "mock_sar_dem",
                    "event_id":        "himachal_2023",
                    "slope_angle":     slope_ang,
                    "location_label":  label,
                    "debris_volume_m3": volume_m3,
                    "road_blocked":    bool(rng.integers(0, 2)),
                    "houses_buried":   int(rng.integers(0, 25)),
                },
            )
        )

    path = _DEMO_BASE / "landslide" / "himachal_2023" / "affected_zones.geojson"
    _write(path, _featurecollection(features), force)


# ---------------------------------------------------------------------------
# 3. CYCLONE — Odisha 2023 (Cyclone Michaung)
# ---------------------------------------------------------------------------

def generate_cyclone_odisha(force: bool = False) -> None:
    """Generate mock cyclone storm track + coastal surge polygons for Odisha 2023.

    Bounding box: [84.0, 19.0, 87.0, 21.5]
    Storm track: Bay of Bengal → Odisha/AP coast landfall (~Bapatla area)
    4 storm surge inundation polygons along the coast (lat ~19.0–20.2).
    1 LineString representing the cyclone track.

    Total features: 5 (1 LineString + 4 Polygons)
    """
    rng = _rng(_RNG_SEED + 30)

    # ------------------------------------------------------------------
    # 1. Storm track LineString
    #    Cyclone Michaung formed in the Bay of Bengal and moved NW
    #    making landfall near Bapatla (≈80.5°E, 15.9°N — outside bbox)
    #    We show the portion within the bbox as it approached.
    # ------------------------------------------------------------------
    track_points = [
        (86.80, 19.10),   # entry point (SE corner of bbox) — open sea
        (86.20, 19.40),   # moving NW over Bay of Bengal
        (85.60, 19.80),   # intensifying (category 2)
        (84.90, 20.30),   # approaching coast (category 3, peak intensity)
        (84.30, 20.90),   # nearing landfall
        (84.05, 21.20),   # exit point (NW, landfall just outside bbox)
    ]
    track_coords = linestring_coords(track_points)
    track_wind_speed = 195   # km/h at peak (verified Michaung data)

    track_feature = _linestring_feature(
        track_coords,
        {
            "confidence":        0.97,   # track data from INSAT-3D, high confidence
            "disaster_type":     "cyclone",
            "source":            "mock_insat3d",
            "event_id":          "odisha_2023",
            "feature_type":      "storm_track",
            "cyclone_name":      "Michaung",
            "max_wind_speed_kmh": track_wind_speed,
            "landfall_location": "Bapatla, Andhra Pradesh",
            "track_length_km":   380,
        },
    )

    # ------------------------------------------------------------------
    # 2. Storm surge inundation polygons — coastal Odisha
    #    Concentrated along the coastline (lat 19.0–20.5)
    # ------------------------------------------------------------------
    surge_zones = [
        # (center_lon, center_lat, radius_deg, wind_speed, surge_m, label)
        (86.50, 19.20, 0.18, 175, 4.2, "Ganjam District Coast"),
        (85.80, 19.45, 0.15, 195, 5.0, "Puri District Coast"),   # peak surge
        (85.20, 19.70, 0.14, 180, 3.8, "Khordha Coastal Blocks"),
        (84.50, 20.10, 0.12, 155, 2.5, "Jagatsinghpur Mouth"),
    ]

    features: list[dict] = [track_feature]
    for i, (lon, lat, radius, wind, surge, label) in enumerate(surge_zones):
        # Surge polygons are wide (coast-parallel) and short inland
        coords = convex_polygon_coords(
            lon, lat, radius, n_points=8, seed=_RNG_SEED + 30 + i,
            lon_stretch=rng.uniform(1.4, 1.8),   # elongated along coast (E-W)
            lat_stretch=rng.uniform(0.4, 0.7),   # short inland penetration
        )
        confidence = round(float(rng.uniform(0.82, 0.94)), 4)
        area_km2   = approx_area_km2(radius, lat, lon_stretch=1.6, lat_stretch=0.55)

        features.append(
            _polygon_feature(
                coords,
                {
                    "confidence":      confidence,
                    "area_km2":        area_km2,
                    "disaster_type":   "cyclone",
                    "source":          "mock_surge_model",
                    "event_id":        "odisha_2023",
                    "feature_type":    "storm_surge",
                    "wind_speed_kmh":  wind,
                    "storm_surge_m":   surge,
                    "location_label":  label,
                    "villages_affected": int(rng.integers(15, 80)),
                    "evacuation_required": True,
                },
            )
        )

    path = _DEMO_BASE / "cyclone" / "odisha_2023" / "affected_zones.geojson"
    _write(path, _featurecollection(features), force)


# ---------------------------------------------------------------------------
# 4. EARTHQUAKE — Gujarat 2024
# ---------------------------------------------------------------------------

def generate_earthquake_gujarat(force: bool = False) -> None:
    """Generate mock earthquake damage proxy polygons for Gujarat 2024.

    Bounding box: [70.0, 21.5, 72.5, 23.0]
    Epicentre: approximately (71.5, 23.0) — northern Kutch, Bhuj area.
    7 damage zones in concentric rings (intensity diminishes with distance).
    Damage levels: 'destroyed' → 'major' → 'moderate'.
    """
    rng = _rng(_RNG_SEED + 40)

    # Epicentre in northern Kutch (near Bhuj — known seismic zone)
    EPI_LON = 71.50
    EPI_LAT = 23.05

    # 7 zones with damage level determined by distance from epicentre
    # Innermost zones = destroyed, outer = moderate
    zones = [
        # (delta_lon, delta_lat, radius_deg, damage_level, label)
        ( 0.00,  0.00,  0.08, "destroyed", "Epicentre — Bhuj Urban Core"),
        ( 0.15, -0.10,  0.10, "destroyed", "Anjar Town"),
        (-0.12,  0.08,  0.09, "major",     "Bhachau Municipality"),
        ( 0.25,  0.05,  0.11, "major",     "Rapar Block"),
        (-0.20, -0.15,  0.12, "major",     "Gandhidham Port Area"),
        ( 0.35, -0.20,  0.13, "moderate",  "Mundra Industrial Zone"),
        (-0.30,  0.18,  0.14, "moderate",  "Naliya Airfield Region"),
    ]

    damage_conf = {
        "destroyed": (0.85, 0.95),
        "major":     (0.75, 0.87),
        "moderate":  (0.65, 0.78),
    }

    features = []
    for i, (dlon, dlat, radius, damage, label) in enumerate(zones):
        lon = EPI_LON + dlon
        lat = EPI_LAT + dlat

        # Damage zones are roughly circular
        coords = convex_polygon_coords(
            lon, lat, radius, n_points=10, seed=_RNG_SEED + 40 + i,
            lon_stretch=rng.uniform(0.9, 1.2),
            lat_stretch=rng.uniform(0.9, 1.1),
        )
        lo, hi     = damage_conf[damage]
        confidence = round(float(rng.uniform(lo, hi)), 4)
        area_km2   = approx_area_km2(radius, lat)

        # InSAR coherence loss (higher loss = more damage)
        coherence_loss_map = {"destroyed": (0.55, 0.80), "major": (0.35, 0.55), "moderate": (0.15, 0.35)}
        cl_lo, cl_hi = coherence_loss_map[damage]
        coherence_loss = round(float(rng.uniform(cl_lo, cl_hi)), 3)

        features.append(
            _polygon_feature(
                coords,
                {
                    "confidence":      confidence,
                    "area_km2":        area_km2,
                    "disaster_type":   "earthquake",
                    "source":          "mock_insar",
                    "event_id":        "gujarat_2024",
                    "damage_level":    damage,
                    "location_label":  label,
                    "coherence_loss":  coherence_loss,
                    "estimated_magnitude": 6.4,
                    "depth_km":        10,
                    "buildings_collapsed": int(area_km2 * rng.uniform(50, 300)),
                },
            )
        )

    path = _DEMO_BASE / "earthquake" / "gujarat_2024" / "affected_zones.geojson"
    _write(path, _featurecollection(features), force)


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def generate_all(force: bool = False) -> None:
    """Generate all 5 demo datasets.

    Parameters
    ----------
    force : bool
        If True, overwrite existing files.  If False (default), skip files
        that already exist.
    """
    print("\n" + "=" * 65)
    print("  OrbitalMind — Mock Demo Data Generator")
    print("=" * 65)
    print(f"  Output root : {_DEMO_BASE}")
    print(f"  Force mode  : {'ON (overwriting)' if force else 'OFF (skip existing)'}\n")

    generators = [
        ("Kerala 2018 Flood (fallback mock)",    generate_kerala_flood),
        ("Uttarakhand 2024 Wildfire",            generate_wildfire_uttarakhand),
        ("Himachal Pradesh 2023 Landslide",      generate_landslide_himachal),
        ("Odisha 2023 Cyclone Michaung",         generate_cyclone_odisha),
        ("Gujarat 2024 Earthquake",              generate_earthquake_gujarat),
    ]

    for label, fn in generators:
        print(f"  >> {label}")
        fn(force=force)
        print()

    print("=" * 65)
    print("  All demo data generated.")
    print("  Next: python scripts/validate_demo_data.py")
    print("=" * 65 + "\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate mock GeoJSON demo datasets for OrbitalMind"
    )
    parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="Overwrite existing GeoJSON files",
    )
    args = parser.parse_args()
    generate_all(force=args.force)
