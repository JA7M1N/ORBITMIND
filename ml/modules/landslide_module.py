"""
OrbitalMind — Landslide Detection Module (DEMO)
================================================
Planned detection pipeline (Phase 2):
  Sentinel-1 SAR amplitude change  +  SRTM slope layer  →  landslide mapping

Demo event: Himachal Pradesh Landslide 2023
  bbox: [76.5, 31.0, 78.0, 32.5]
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ml.disaster_module import DisasterModule

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEMO_BASE  = _REPO_ROOT / "backend" / "demo_data" / "landslide"


class LandslideModule(DisasterModule):
    """Landslide susceptibility mapping via Sentinel-1 SAR + SRTM DEM.

    Status
    ------
    **DEMO** — serves pre-generated mock GeoJSON.
    Phase 2 will fuse SAR amplitude change (VV polarisation) with SRTM-derived
    slope and curvature layers, applying a random-forest classifier to flag
    high-susceptibility zones post-event.

    Priority weights (from OrbitalMind architecture spec)
    -----------------------------------------------------
    population  0.40
    infra       0.25
    access      0.25  ← high — roads are often primary casualty in landslides
    intensity   0.10
    """

    disaster_type    : str       = "landslide"
    display_name     : str       = "Landslide Detection"
    icon             : str       = "🏔️"
    color            : str       = "#92400e"
    satellite_sources: list[str] = [
        "COPERNICUS/S1_GRD",      # Sentinel-1 SAR amplitude change
        "USGS/SRTMGL1_003",       # SRTM 30m DEM → slope / curvature
    ]
    detection_method : str = (
        "Sentinel-1 SAR amplitude change detection + SRTM slope-based susceptibility"
    )
    affected_infra_types: list[str] = [
        "hospital",
        "school",
        "bridge",
        "highway",
    ]
    priority_weights: dict[str, float] = {
        "population": 0.40,
        "infra":      0.25,
        "access":     0.25,
        "intensity":  0.10,
    }
    is_live       : bool = False
    demo_event_id : str  = "himachal_2023"

    def get_demo_data(self, event_id: str = "himachal_2023") -> dict[str, Any]:
        """Load pre-generated landslide zones from disk (DEMO_MODE=True).

        Reads ``backend/demo_data/landslide/{event_id}/affected_zones.geojson``.

        Parameters
        ----------
        event_id : str
            Demo event slug, defaults to ``"himachal_2023"``.

        Returns
        -------
        dict
            Standardised OrbitalMind response with ``affected_zones`` GeoJSON.

        Raises
        ------
        FileNotFoundError
            If the expected GeoJSON is absent.
        """
        geojson_path = _DEMO_BASE / event_id / "affected_zones.geojson"
        if not geojson_path.exists():
            raise FileNotFoundError(
                f"Landslide demo data not found at: {geojson_path}"
            )

        with geojson_path.open("r", encoding="utf-8") as fh:
            geojson = json.load(fh)

        features   = geojson.get("features", [])
        total_area = sum(f["properties"].get("area_km2", 0.0) for f in features)

        return {
            "event_id":       event_id,
            "disaster_type":  self.disaster_type,
            "source":         "demo",
            "affected_zones": geojson,
            "summary_stats":  {
                "total_area_km2":  round(total_area, 2),
                "mean_confidence": 0.84,
                "peak_intensity":  0.79,
            },
        }

    def run_detection(
        self,
        event_id: str,
        bbox: list[float],
        date_range: tuple[str, str],
    ) -> dict[str, Any]:
        """Live Sentinel-1 + SRTM landslide detection — Phase 2.

        Parameters
        ----------
        event_id : str
            UUID of the disaster event row.
        bbox : list[float]
            ``[min_lon, min_lat, max_lon, max_lat]`` EPSG:4326.
        date_range : tuple[str, str]
            ISO-8601 start/end date pair.

        Raises
        ------
        NotImplementedError
            Module coming in Phase 2.
        """
        raise NotImplementedError("LandslideModule: live inference coming in Phase 2.")
