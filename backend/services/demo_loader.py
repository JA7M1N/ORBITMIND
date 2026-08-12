"""
OrbitalMind — Demo Data Loader
================================
Loads pre-computed GeoJSON and priority data from disk for DEMO_MODE.

All methods:
  - Return in < 50 ms (disk reads, in-memory cache after first call)
  - Never touch the database or run ML inference
  - Work for all 5 disaster types

Cache
-----
A module-level dict ``_CACHE`` stores loaded GeoJSON by (disaster_type, event_id)
key.  Cache is populated on first access and lives for the server process lifetime.
Call ``clear_cache()`` in tests to reset between runs.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

# ── Paths ─────────────────────────────────────────────────────────────────────
_REPO     = Path(__file__).resolve().parents[2]
_DEMO_DIR = _REPO / "backend" / "demo_data"
_MANIFEST = _DEMO_DIR / "events_manifest.json"

# ── In-memory cache {(disaster_type, event_id): geojson_dict} ─────────────────
_CACHE: dict[tuple[str, str], dict] = {}

# GeoJSON filename preference per disaster type
_GEOJSON_NAMES: dict[str, list[str]] = {
    "flood":      ["flood_mask.geojson", "affected_zones.geojson"],
    "wildfire":   ["affected_zones.geojson", "burn_mask.geojson"],
    "landslide":  ["affected_zones.geojson", "slide_mask.geojson"],
    "cyclone":    ["affected_zones.geojson", "impact_zones.geojson"],
    "earthquake": ["affected_zones.geojson", "damage_zones.geojson"],
}

# ── Hardcoded realistic priority data for DEMO_MODE (no DB needed) ────────────
# Source: Census 2011 + HMIS 2018-19 + UDISE+ + SAR-derived flood depth proxy
_DEMO_PRIORITY: dict[str, list[dict]] = {
    "kerala_2018": [
        {"rank": 1, "zone": "Ernakulam",          "score": 0.87, "hospitals": 18, "schools": 45, "bridges": 4, "pop": 3282388},
        {"rank": 2, "zone": "Alappuzha",           "score": 0.82, "hospitals":  8, "schools": 29, "bridges": 6, "pop": 2127789},
        {"rank": 3, "zone": "Thrissur",            "score": 0.71, "hospitals": 12, "schools": 38, "bridges": 3, "pop": 3121200},
        {"rank": 4, "zone": "Palakkad",            "score": 0.63, "hospitals":  7, "schools": 41, "bridges": 2, "pop": 2809934},
        {"rank": 5, "zone": "Malappuram",          "score": 0.59, "hospitals":  9, "schools": 52, "bridges": 2, "pop": 4112920},
        {"rank": 6, "zone": "Kozhikode",           "score": 0.54, "hospitals":  9, "schools": 36, "bridges": 2, "pop": 3086293},
        {"rank": 7, "zone": "Idukki",              "score": 0.52, "hospitals":  5, "schools": 22, "bridges": 4, "pop": 1108974},
        {"rank": 8, "zone": "Kottayam",            "score": 0.49, "hospitals":  6, "schools": 27, "bridges": 2, "pop": 1974551},
    ],
    "uttarakhand_2024": [
        {"rank": 1, "zone": "Chamoli",     "score": 0.81, "hospitals": 4, "schools": 12, "bridges": 5, "pop": 391605},
        {"rank": 2, "zone": "Rudraprayag", "score": 0.74, "hospitals": 3, "schools":  9, "bridges": 4, "pop": 242285},
        {"rank": 3, "zone": "Uttarkashi",  "score": 0.68, "hospitals": 3, "schools": 11, "bridges": 3, "pop": 330086},
        {"rank": 4, "zone": "Tehri Garhwal","score":0.61, "hospitals": 5, "schools": 18, "bridges": 3, "pop": 618931},
        {"rank": 5, "zone": "Pauri Garhwal","score":0.55, "hospitals": 4, "schools": 14, "bridges": 2, "pop": 687271},
    ],
    "himachal_2023": [
        {"rank": 1, "zone": "Shimla",   "score": 0.79, "hospitals": 8, "schools": 22, "bridges": 4, "pop": 814010},
        {"rank": 2, "zone": "Kullu",    "score": 0.72, "hospitals": 4, "schools": 14, "bridges": 6, "pop": 437903},
        {"rank": 3, "zone": "Mandi",    "score": 0.64, "hospitals": 6, "schools": 19, "bridges": 3, "pop": 999777},
        {"rank": 4, "zone": "Solan",    "score": 0.56, "hospitals": 5, "schools": 16, "bridges": 2, "pop": 580320},
        {"rank": 5, "zone": "Sirmaur",  "score": 0.49, "hospitals": 3, "schools": 12, "bridges": 3, "pop": 529855},
        {"rank": 6, "zone": "Chamba",   "score": 0.43, "hospitals": 3, "schools": 10, "bridges": 4, "pop": 519080},
    ],
    "odisha_2023": [
        {"rank": 1, "zone": "Srikakulam",  "score": 0.83, "hospitals": 6, "schools": 24, "bridges": 3, "pop": 2699072},
        {"rank": 2, "zone": "Vizianagaram","score": 0.76, "hospitals": 5, "schools": 20, "bridges": 2, "pop": 2342868},
        {"rank": 3, "zone": "Puri",        "score": 0.71, "hospitals": 7, "schools": 18, "bridges": 2, "pop": 1498604},
        {"rank": 4, "zone": "Khordha",     "score": 0.65, "hospitals": 9, "schools": 28, "bridges": 2, "pop": 2246341},
        {"rank": 5, "zone": "Ganjam",      "score": 0.58, "hospitals": 6, "schools": 22, "bridges": 2, "pop": 3520151},
    ],
    "gujarat_2024": [
        {"rank": 1, "zone": "Kutch",     "score": 0.84, "hospitals": 7, "schools": 19, "bridges": 3, "pop": 2090313},
        {"rank": 2, "zone": "Rajkot",    "score": 0.73, "hospitals": 12,"schools": 31, "bridges": 2, "pop": 3800000},
        {"rank": 3, "zone": "Jamnagar",  "score": 0.65, "hospitals": 8, "schools": 22, "bridges": 2, "pop": 2159130},
        {"rank": 4, "zone": "Morbi",     "score": 0.61, "hospitals": 4, "schools": 14, "bridges": 3, "pop": 993347},
        {"rank": 5, "zone": "Surendranagar","score":0.54,"hospitals": 5, "schools": 17, "bridges": 2, "pop": 1756268},
        {"rank": 6, "zone": "Patan",     "score": 0.47, "hospitals": 4, "schools": 13, "bridges": 2, "pop": 1343734},
        {"rank": 7, "zone": "Banaskantha","score":0.41, "hospitals": 5, "schools": 15, "bridges": 2, "pop": 3120673},
    ],
}

# ── Module info block added to every DetectionResult ─────────────────────────
_MODULE_INFO: dict[str, dict] = {
    "flood": {
        "module":           "FloodModule",
        "model":            "Attention U-Net (ResNet-34)",
        "satellite":        "Sentinel-1 SAR (C-band, VV+VH)",
        "resolution_m":     10,
        "inference_time_s": 4.2,
        "phase":            1,
        "is_live":          True,
    },
    "wildfire": {
        "module":           "WildfireModule",
        "model":            "dNBR + Random Forest",
        "satellite":        "Sentinel-2 MSI (SWIR 11+12)",
        "resolution_m":     20,
        "inference_time_s": 2.8,
        "phase":            2,
        "is_live":          False,
    },
    "landslide": {
        "module":           "LandslideModule",
        "model":            "SAR Coherence Change + SlopeSI",
        "satellite":        "Sentinel-1 InSAR + SRTM DEM",
        "resolution_m":     30,
        "inference_time_s": 3.5,
        "phase":            2,
        "is_live":          False,
    },
    "cyclone": {
        "module":           "CycloneModule",
        "model":            "Dvorak + Storm Surge Model",
        "satellite":        "INSAT-3D (IR + WV channels)",
        "resolution_m":     1000,
        "inference_time_s": 1.9,
        "phase":            2,
        "is_live":          False,
    },
    "earthquake": {
        "module":           "EarthquakeModule",
        "model":            "D-InSAR + ShakeMap PGA",
        "satellite":        "Sentinel-1 SAR (InSAR pair)",
        "resolution_m":     30,
        "inference_time_s": 5.1,
        "phase":            2,
        "is_live":          False,
    },
}


# ── Public API ────────────────────────────────────────────────────────────────

def clear_cache() -> None:
    """Clear in-memory GeoJSON cache. Useful in tests."""
    _CACHE.clear()


def load_all_events() -> list[dict]:
    """Read and return all events from events_manifest.json.

    Returns
    -------
    list[dict]
        Each dict has: event_id, disaster_type, display_name, region,
        date_start, date_end, status, data_source, thumbnail_color, bbox.

    Raises
    ------
    FileNotFoundError
        If the manifest doesn't exist (run generate_mock_data.py).
    """
    if not _MANIFEST.exists():
        raise FileNotFoundError(
            f"events_manifest.json not found at {_MANIFEST}. "
            "Run: python scripts/generate_mock_data.py"
        )
    data = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    return data.get("events", [])


def _find_geojson(disaster_type: str, event_id: str) -> Path:
    """Locate the GeoJSON file for a given event."""
    base = _DEMO_DIR / disaster_type / event_id
    for name in _GEOJSON_NAMES.get(disaster_type, ["affected_zones.geojson"]):
        p = base / name
        if p.exists():
            return p
    raise FileNotFoundError(
        f"No GeoJSON found for {disaster_type}/{event_id} in {base}. "
        "Expected one of: " + ", ".join(_GEOJSON_NAMES.get(disaster_type, []))
    )


def load_demo_affected_zones(event_id: str, disaster_type: str) -> dict:
    """Load the affected-zone GeoJSON for a demo event.

    Results are cached in ``_CACHE`` after first load so repeated calls
    return in < 1 ms.

    Parameters
    ----------
    event_id : str
        Event slug (e.g. ``kerala_2018``).
    disaster_type : str
        One of: flood, wildfire, landslide, cyclone, earthquake.

    Returns
    -------
    dict
        Raw GeoJSON FeatureCollection as parsed from disk.

    Raises
    ------
    FileNotFoundError
        If the GeoJSON file does not exist.
    """
    key = (disaster_type, event_id)
    if key in _CACHE:
        return _CACHE[key]

    t0   = time.perf_counter()
    path = _find_geojson(disaster_type, event_id)
    data = json.loads(path.read_text(encoding="utf-8"))
    elapsed_ms = (time.perf_counter() - t0) * 1000

    _CACHE[key] = data
    return data


def load_demo_priority(event_id: str) -> list[dict]:
    """Return pre-computed priority zone rankings for a demo event.

    Uses hardcoded district data (Census 2011 population, HMIS hospitals,
    UDISE schools) — no database required in DEMO_MODE.

    Parameters
    ----------
    event_id : str
        Event slug — must match a key in ``_DEMO_PRIORITY``.

    Returns
    -------
    list[dict]
        Sorted by rank ascending (rank 1 = highest priority).
        Each dict: rank, zone, score, hospitals, schools, bridges, pop.
    """
    norm = event_id.replace("-", "_")
    return _DEMO_PRIORITY.get(norm, [])


def build_detection_result(
    event_id:     str,
    disaster_type: str,
    event_meta:   dict,
) -> dict:
    """Build a full DetectionResult dict from demo data.

    Combines:
    - GeoJSON FeatureCollection from disk
    - Pre-computed priority rankings
    - Module info block
    - Aggregate stats computed from the GeoJSON features

    Parameters
    ----------
    event_id : str
        Event slug.
    disaster_type : str
        Module routing key.
    event_meta : dict
        Full event record from events_manifest.json.

    Returns
    -------
    dict
        Complete DetectionResult ready for the frontend / API response.
    """
    geojson   = load_demo_affected_zones(event_id, disaster_type)
    priority  = load_demo_priority(event_id)
    mod_info  = _MODULE_INFO.get(disaster_type, {})
    features  = geojson.get("features", [])

    # Aggregate stats from GeoJSON features
    confidences = [
        float(f.get("properties", {}).get("confidence", 0.5))
        for f in features if f.get("properties")
    ]
    areas = [
        float(f.get("properties", {}).get("area_km2", 0))
        for f in features if f.get("properties", {}).get("area_km2")
    ]

    avg_conf   = round(sum(confidences) / len(confidences), 4) if confidences else 0.0
    total_area = round(sum(areas), 2)

    # Attach priority metadata to features
    enriched_features = _enrich_features(features, priority, disaster_type)

    stats = _build_stats(disaster_type, enriched_features, avg_conf, total_area, event_meta)

    return {
        "event_id":      event_id,
        "disaster_type": disaster_type,
        "display_name":  event_meta.get("display_name", event_id),
        "region":        event_meta.get("region", ""),
        "date":          event_meta.get("date_start", ""),
        "status":        "demo",
        "module_info":   mod_info,
        "affected_zones_geojson": {
            "type":     "FeatureCollection",
            "features": enriched_features,
        },
        "priority_zones": priority,
        "stats":          stats,
    }


def _enrich_features(
    features: list[dict],
    priority: list[dict],
    disaster_type: str,
) -> list[dict]:
    """Add priority metadata to GeoJSON feature properties."""
    enriched = []
    for i, feat in enumerate(features):
        props = dict(feat.get("properties") or {})
        # Attach priority data cyclically if fewer priority zones than features
        if priority and i < len(priority):
            p = priority[i]
            props["priority_rank"]      = p["rank"]
            props["priority_score"]     = p["score"]
            props["hospitals_affected"] = p["hospitals"]
            props["schools_affected"]   = p["schools"]
            props["bridges_affected"]   = p["bridges"]
            props["zone_name"]          = p["zone"]
            props["population"]         = p["pop"]
        enriched.append({**feat, "properties": props})
    # Sort by priority_score desc
    enriched.sort(
        key=lambda f: f.get("properties", {}).get("priority_score", 0),
        reverse=True,
    )
    return enriched


def _build_stats(
    disaster_type: str,
    features: list[dict],
    avg_conf: float,
    total_area: float,
    event_meta: dict,
) -> dict:
    """Build disaster-specific stats dict from enriched features."""
    base = {
        "zone_count":     len(features),
        "avg_confidence": avg_conf,
        "total_area_km2": total_area,
    }

    if disaster_type == "flood":
        base.update({
            "total_flooded_area_km2": total_area,
            "high_confidence_zones":  sum(
                1 for f in features
                if float(f.get("properties", {}).get("confidence", 0)) > 0.75
            ),
            "max_water_depth_m":      max(
                (float(f.get("properties", {}).get("water_depth_m", 0)) for f in features),
                default=0.0,
            ),
            "people_affected":        sum(
                int(f.get("properties", {}).get("population", 0)) for f in features
            ),
        })
    elif disaster_type == "wildfire":
        base.update({
            "total_burned_area_km2": total_area,
            "high_severity_pct":     round(
                sum(
                    1 for f in features
                    if str(f.get("properties", {}).get("burn_severity", "")).lower() == "high"
                ) / max(len(features), 1) * 100, 1
            ),
            "fire_perimeter_km":     round(total_area ** 0.5 * 4, 1),
        })
    elif disaster_type == "landslide":
        base.update({
            "total_slide_area_km2": total_area,
            "avg_slope_angle_deg":  round(
                sum(
                    float(f.get("properties", {}).get("slope_angle_deg", 35))
                    for f in features
                ) / max(len(features), 1), 1
            ),
            "roads_blocked":        sum(
                int(f.get("properties", {}).get("roads_blocked", 0)) for f in features
            ),
        })
    elif disaster_type == "cyclone":
        base.update({
            "max_wind_speed_kmh":  float(event_meta.get("max_wind_kmh", 110)),
            "storm_surge_max_m":   float(event_meta.get("storm_surge_m", 2.5)),
            "landfall_district":   event_meta.get("landfall_district", "Coastal"),
            "cyclone_category":    event_meta.get("cyclone_category", "Severe"),
        })
    elif disaster_type == "earthquake":
        base.update({
            "total_damage_area_km2": total_area,
            "max_pga_g":            float(event_meta.get("max_pga_g", 0.35)),
            "magnitude":            float(event_meta.get("magnitude", 5.8)),
            "depth_km":             float(event_meta.get("depth_km", 10)),
        })

    return base
