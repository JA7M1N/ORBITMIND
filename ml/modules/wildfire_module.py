"""
OrbitalMind — Wildfire Detection Module (DEMO)
===============================================
Planned detection pipeline (Phase 2):
  Sentinel-2 SWIR bands (B11, B12)  →  NBR ratio  →  burn-scar mapping

Demo event: Uttarakhand Wildfire 2024
  bbox: [78.5, 29.5, 80.5, 31.5]
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ml.disaster_module import DisasterModule

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEMO_BASE  = _REPO_ROOT / "backend" / "demo_data" / "wildfire"


class WildfireModule(DisasterModule):
    """Wildfire burn-scar detection via Sentinel-2 NBR ratio.

    Status
    ------
    **DEMO** — serves pre-generated mock GeoJSON.
    Real inference (Phase 2) will use Sentinel-2 SWIR B11/B12 to compute
    the Normalized Burn Ratio (NBR) and delta-NBR (dNBR) for burn severity
    classification.

    Priority weights (from OrbitalMind architecture spec)
    -----------------------------------------------------
    population  0.35
    infra       0.35  ← equal weight — utilities & hospitals equally at risk
    access      0.10
    intensity   0.20  ← higher than flood — burn severity drives urgency
    """

    disaster_type    : str        = "wildfire"
    display_name     : str        = "Wildfire Detection"
    icon             : str        = "🔥"
    color            : str        = "#b91c1c"
    satellite_sources: list[str]  = [
        "COPERNICUS/S2_SR_HARMONIZED",      # Sentinel-2 SWIR (B11, B12)
        "MODIS/061/MOD14A1",                # MODIS active fire (validation)
    ]
    detection_method : str = (
        "Sentinel-2 SWIR NBR / dNBR burn-severity ratio analysis"
    )
    affected_infra_types: list[str] = [
        "hospital",
        "school",
        "power_line",
        "highway",
    ]
    priority_weights: dict[str, float] = {
        "population": 0.35,
        "infra":      0.35,
        "access":     0.10,
        "intensity":  0.20,
    }
    is_live       : bool = False
    demo_event_id : str  = "uttarakhand_2024"

    def get_demo_data(self, event_id: str = "uttarakhand_2024") -> dict[str, Any]:
        """Load pre-generated wildfire zones from disk (DEMO_MODE=True).

        Reads ``backend/demo_data/wildfire/{event_id}/affected_zones.geojson``.

        Parameters
        ----------
        event_id : str
            Demo event slug, defaults to ``"uttarakhand_2024"``.

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
                f"Wildfire demo data not found at: {geojson_path}"
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
                "mean_confidence": 0.91,   # representative mock value
                "peak_intensity":  0.87,   # dNBR high-severity threshold
            },
        }

    def run_detection(
        self,
        event_id: str,
        bbox: list[float],
        date_range: tuple[str, str],
    ) -> dict[str, Any]:
        """Live Sentinel-2 NBR wildfire detection — Phase 2.

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
        raise NotImplementedError("WildfireModule: live inference coming in Phase 2.")
