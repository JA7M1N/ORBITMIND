"""
OrbitalMind — Earthquake Detection Module (DEMO)
=================================================
Planned detection pipeline (Phase 2):
  Sentinel-1 InSAR coherence change  →  surface displacement mapping

Demo event: Gujarat Earthquake 2024
  bbox: [70.0, 21.5, 72.5, 23.0]
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ml.disaster_module import DisasterModule

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEMO_BASE  = _REPO_ROOT / "backend" / "demo_data" / "earthquake"


class EarthquakeModule(DisasterModule):
    """Earthquake structural damage assessment via Sentinel-1 InSAR coherence.

    Status
    ------
    **DEMO** — serves pre-generated mock GeoJSON.
    Phase 2 will compute coherence change (Δγ) between pre- and post-event
    Sentinel-1 SLC pairs using the SNAP ESA toolbox (via snappy Python API).
    Low coherence regions indicate surface disruption or building collapse.

    Priority weights (from OrbitalMind architecture spec)
    -----------------------------------------------------
    population  0.30
    infra       0.40  ← highest — structural damage to hospitals is critical
    access      0.20
    intensity   0.10
    """

    disaster_type    : str       = "earthquake"
    display_name     : str       = "Earthquake Detection"
    icon             : str       = "🌍"
    color            : str       = "#d97706"
    satellite_sources: list[str] = [
        "COPERNICUS/S1_GRD",      # Sentinel-1 SAR (InSAR coherence pairs)
        "USGS/SRTMGL1_003",       # SRTM DEM for topographic phase removal
    ]
    detection_method : str = (
        "Sentinel-1 InSAR coherence change → surface displacement & damage proxy mapping"
    )
    affected_infra_types: list[str] = [
        "hospital",
        "school",
        "bridge",
        "highway",
        "dam",
    ]
    priority_weights: dict[str, float] = {
        "population": 0.30,
        "infra":      0.40,
        "access":     0.20,
        "intensity":  0.10,
    }
    is_live       : bool = False
    demo_event_id : str  = "gujarat_2024"

    def get_demo_data(self, event_id: str = "gujarat_2024") -> dict[str, Any]:
        """Load pre-generated earthquake damage zones from disk (DEMO_MODE=True).

        Reads ``backend/demo_data/earthquake/{event_id}/affected_zones.geojson``.

        Parameters
        ----------
        event_id : str
            Demo event slug, defaults to ``"gujarat_2024"``.

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
                f"Earthquake demo data not found at: {geojson_path}"
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
                "mean_confidence": 0.82,
                "peak_intensity":  0.76,   # coherence loss magnitude
            },
        }

    def run_detection(
        self,
        event_id: str,
        bbox: list[float],
        date_range: tuple[str, str],
    ) -> dict[str, Any]:
        """Live Sentinel-1 InSAR earthquake damage assessment — Phase 2.

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
        raise NotImplementedError("EarthquakeModule: live inference coming in Phase 2.")
