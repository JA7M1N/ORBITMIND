"""
OrbitalMind — Disaster Module Abstract Base Class
=================================================
Every disaster module (Flood, Wildfire, Landslide, Cyclone, Earthquake)
must subclass ``DisasterModule`` and implement the two abstract methods.

Plugin contract
---------------
1.  Declare all metadata fields as class-level attributes.
2.  Implement ``run_detection()`` for live satellite inference.
3.  Implement ``get_demo_data()`` for DEMO_MODE (reads pre-generated GeoJSON from disk).

VRAM rule
---------
Never run the U-Net pipeline and Ollama concurrently.
The orchestrator (ml_service.py) clears GPU memory between the two stages.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class DisasterModule(ABC):
    """Abstract base class that every OrbitalMind disaster module must extend.

    Class-level attributes
    ----------------------
    disaster_type : str
        Lowercase snake_case identifier used as a routing key across the
        platform (e.g. ``"flood"``, ``"wildfire"``).
    display_name : str
        Human-readable name shown in the UI (e.g. ``"Flood Detection"``).
    icon : str
        Emoji icon displayed in the DisasterNav component.
    color : str
        Hex colour used for map overlays and UI accents.
    satellite_sources : list[str]
        Google Earth Engine asset IDs for the primary data sources.
    detection_method : str
        Short description of the algorithmic approach.
    affected_infra_types : list[str]
        Infrastructure categories queried from PostGIS during scoring
        (subset of: ``"hospital"``, ``"school"``, ``"bridge"``, ``"highway"``).
    priority_weights : dict[str, float]
        Weights for the shared priority-scoring formula::

            Score = w_pop×(pop/max_pop) + w_infra×infra_score
                  + w_access×(1 - accessibility) + w_intensity×intensity

        Keys: ``"population"``, ``"infra"``, ``"access"``, ``"intensity"``.
        Values must sum to 1.0.
    is_live : bool
        ``True`` if the module runs real ML inference; ``False`` for demo stubs.
    demo_event_id : str
        Canonical demo event slug used when DEMO_MODE=True.
    """

    # ------------------------------------------------------------------ #
    # Metadata — override in every subclass                               #
    # ------------------------------------------------------------------ #
    disaster_type: str = ""
    display_name: str = ""
    icon: str = ""
    color: str = "#ffffff"
    satellite_sources: list[str] = []
    detection_method: str = ""
    affected_infra_types: list[str] = []
    priority_weights: dict[str, float] = {}
    is_live: bool = False
    demo_event_id: str = ""

    # ------------------------------------------------------------------ #
    # Concrete helpers                                                     #
    # ------------------------------------------------------------------ #

    def get_module_info(self) -> dict[str, Any]:
        """Return a serialisable dict of all module metadata.

        This is called by ``list_modules()`` in the registry and by the
        ``GET /api/modules`` endpoint to populate the frontend module switcher.

        Returns
        -------
        dict
            Keys mirror the class attributes defined above, plus a computed
            ``"status"`` field (``"live"`` | ``"demo"``).

        Example
        -------
        >>> from ml.modules.flood_module import FloodModule
        >>> FloodModule().get_module_info()
        {
            'disaster_type': 'flood',
            'display_name': 'Flood Detection',
            'icon': '🌊',
            'color': '#1e40af',
            'satellite_sources': [...],
            'detection_method': '...',
            'affected_infra_types': [...],
            'priority_weights': {...},
            'is_live': True,
            'demo_event_id': 'kerala_2018',
            'status': 'live'
        }
        """
        return {
            "disaster_type": self.disaster_type,
            "display_name": self.display_name,
            "icon": self.icon,
            "color": self.color,
            "satellite_sources": self.satellite_sources,
            "detection_method": self.detection_method,
            "affected_infra_types": self.affected_infra_types,
            "priority_weights": self.priority_weights,
            "is_live": self.is_live,
            "demo_event_id": self.demo_event_id,
            "status": "live" if self.is_live else "demo",
        }

    def validate_weights(self) -> bool:
        """Validate that priority_weights values sum to 1.0 (within ±0.01 tolerance).

        Called automatically by the registry on startup to catch misconfigured
        modules early. Raises ``ValueError`` if the sum is out of tolerance.

        Returns
        -------
        bool
            ``True`` if weights are valid.

        Raises
        ------
        ValueError
            If ``priority_weights`` is empty or the sum deviates from 1.0
            by more than 0.01.
        """
        if not self.priority_weights:
            raise ValueError(
                f"[{self.disaster_type}] priority_weights must not be empty."
            )
        total = sum(self.priority_weights.values())
        if abs(total - 1.0) > 0.01:
            raise ValueError(
                f"[{self.disaster_type}] priority_weights sum to {total:.4f}, expected 1.0."
            )
        return True

    # ------------------------------------------------------------------ #
    # Abstract interface — implement in every subclass                    #
    # ------------------------------------------------------------------ #

    @abstractmethod
    def run_detection(
        self,
        event_id: str,
        bbox: list[float],
        date_range: tuple[str, str],
    ) -> dict[str, Any]:
        """Run live satellite-based disaster detection for the given region.

        This method performs the full ML inference pipeline:
        imagery acquisition via GEE → pre-processing →
        model inference → post-processing → GeoJSON output.

        .. warning::
            VRAM rule — do **not** load Ollama while this method is running.
            The ``ml_service`` orchestrator handles VRAM lifecycle.

        Parameters
        ----------
        event_id : str
            UUID of the ``disaster_events`` row for this analysis run.
        bbox : list[float]
            Bounding box as ``[min_lon, min_lat, max_lon, max_lat]``
            in EPSG:4326.
        date_range : tuple[str, str]
            Start and end dates as ISO-8601 strings, e.g.
            ``("2018-08-01", "2018-08-20")``.

        Returns
        -------
        dict
            Must contain at minimum::

                {
                    "event_id": str,
                    "disaster_type": str,
                    "affected_zones": <GeoJSON FeatureCollection>,
                    "summary_stats": {
                        "total_area_km2": float,
                        "mean_confidence": float,
                        "peak_intensity": float,
                    },
                }

        Raises
        ------
        NotImplementedError
            Raised by stub modules that have not yet implemented live inference.
        RuntimeError
            If the GEE API call fails, imagery is unavailable, or the model
            fails to load within available VRAM.
        """
        ...

    @abstractmethod
    def get_demo_data(self, event_id: str) -> dict[str, Any]:
        """Load pre-generated demo data from disk (DEMO_MODE=True).

        Reads a GeoJSON FeatureCollection from
        ``backend/demo_data/{disaster_type}/{event_id}/`` and returns the
        same schema as ``run_detection()``.

        This path is exercised during hackathon demos — it must respond in
        <100 ms with no network or GPU calls.

        Parameters
        ----------
        event_id : str
            Slug identifying the demo dataset directory (e.g. ``"kerala_2018"``).

        Returns
        -------
        dict
            Same schema as ``run_detection()``.

        Raises
        ------
        FileNotFoundError
            If the expected GeoJSON file is absent from the demo_data directory.
        """
        ...
