"""
OrbitalMind — Cyclone Detection Module (DEMO)
==============================================
Planned detection pipeline (Phase 2):
  INSAT-3D storm track  +  storm surge model  →  coastal inundation mapping

Demo event: Odisha Cyclone 2023 (Cyclone Michaung)
  bbox: [84.0, 19.0, 87.0, 21.5]
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ml.disaster_module import DisasterModule

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEMO_BASE  = _REPO_ROOT / "backend" / "demo_data" / "cyclone"


class CycloneModule(DisasterModule):
    """Cyclone impact assessment via INSAT-3D track + storm surge modelling.

    Status
    ------
    **DEMO** — serves pre-generated mock GeoJSON.
    Phase 2 will ingest INSAT-3D Meteorological Data Product (MDP) track
    data, run a simplified storm-surge model (SLOSH-lite) to delineate
    coastal inundation extents, and combine with wind-speed contours from
    IMD bulletin data.

    Priority weights (from OrbitalMind architecture spec)
    -----------------------------------------------------
    population  0.45  ← highest — coastal population density is critical
    infra       0.30
    access      0.15
    intensity   0.10
    """

    disaster_type    : str       = "cyclone"
    display_name     : str       = "Cyclone Detection"
    icon             : str       = "🌀"
    color            : str       = "#6d28d9"
    satellite_sources: list[str] = [
        "ISRO/INSAT-3D/MDP",              # INSAT-3D meteorological data product
        "NOAA/GFS0P25",                   # GFS wind-field forecast
        "USGS/SRTMGL1_003",               # SRTM DEM for surge run-up
    ]
    detection_method : str = (
        "INSAT-3D storm track + storm-surge modelling → coastal inundation mapping"
    )
    affected_infra_types: list[str] = [
        "hospital",
        "school",
        "bridge",
        "highway",
        "port",
    ]
    priority_weights: dict[str, float] = {
        "population": 0.45,
        "infra":      0.30,
        "access":     0.15,
        "intensity":  0.10,
    }
    is_live       : bool = False
    demo_event_id : str  = "odisha_2023"

    def get_demo_data(self, event_id: str = "odisha_2023") -> dict[str, Any]:
        """Load pre-generated cyclone impact zones from disk (DEMO_MODE=True).

        Reads ``backend/demo_data/cyclone/{event_id}/affected_zones.geojson``.

        Parameters
        ----------
        event_id : str
            Demo event slug, defaults to ``"odisha_2023"``.

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
                f"Cyclone demo data not found at: {geojson_path}"
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
                "mean_confidence": 0.88,
                "peak_intensity":  0.93,   # category-3 landfall wind index
            },
        }

    def run_detection(
        self,
        event_id: str,
        bbox: list[float],
        date_range: tuple[str, str],
    ) -> dict[str, Any]:
        """Live INSAT-3D cyclone impact assessment — Phase 2.

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
        raise NotImplementedError("CycloneModule: live inference coming in Phase 2.")
