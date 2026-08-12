"""
OrbitalMind — ML Service
=========================
Bridge between the module plugin registry and the FastAPI layer.

Responsibilities
----------------
- ``get_available_modules()``      List all 5 modules with metadata + descriptions
- ``run_detection_demo()``         Sub-200ms demo path — reads GeoJSON from disk
- ``run_detection_live()``         Returns task_id instantly, runs inference in background thread
- ``get_event_stats()``            Disaster-specific aggregate stats from GeoJSON properties
- ``get_task_status()``            Poll a background inference task by task_id

Architecture notes
------------------
- Module instances are singletons from the registry — no re-instantiation per request.
- Live inference tasks are tracked in ``_tasks: dict[str, InferenceStatus]``.
  The dict is module-level (process lifetime).  For multi-worker FastAPI deploys,
  swap for Redis or a PostgreSQL ``tasks`` table.
- VRAM rule: ``FloodModule.run_detection()`` calls ``torch.cuda.empty_cache()``
  at the end of its own pipeline.  The ML service does NOT load Ollama — that is
  the LLM service's responsibility.

Thread safety
-------------
``_tasks`` is written only by background threads (one per task_id) and read by
request handlers.  Python's GIL makes dict reads/writes for simple key lookups
effectively atomic, so no explicit lock is needed for the current single-process
setup.  Add ``threading.Lock`` if you switch to multiprocessing workers.
"""

from __future__ import annotations

import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Ensure repo root is on sys.path (supports running from any cwd)
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[2]   # backend/services/ → OrbitalMind/
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# ---------------------------------------------------------------------------
# Registry imports
# ---------------------------------------------------------------------------
from ml.module_registry import get_module, list_modules, DISASTER_MODULES
from ml.disaster_module import DisasterModule
from backend.schemas.ml_schemas import (
    DetectionResult,
    DisasterModuleInfo,
    InferenceStatus,
    PriorityWeights,
    ZoneStats,
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_DEMO_BASE = _REPO_ROOT / "backend" / "demo_data"

# ---------------------------------------------------------------------------
# One-sentence module descriptions (injected into get_available_modules())
# ---------------------------------------------------------------------------
_MODULE_DESCRIPTIONS: dict[str, str] = {
    "flood": (
        "Detects inundated areas using Sentinel-1 SAR VV/VH backscatter change "
        "with a real-time Attention U-Net segmentation pipeline."
    ),
    "wildfire": (
        "Maps post-fire burn scars and severity grades from Sentinel-2 SWIR bands "
        "using the Normalised Burn Ratio (NBR / dNBR) algorithm."
    ),
    "landslide": (
        "Identifies debris-flow extents by fusing Sentinel-1 SAR amplitude change "
        "with SRTM-derived slope and curvature layers."
    ),
    "cyclone": (
        "Tracks storm paths from INSAT-3D meteorological data and models coastal "
        "inundation extents via a simplified storm-surge algorithm."
    ),
    "earthquake": (
        "Generates structural damage proxy maps from Sentinel-1 InSAR coherence "
        "loss between pre- and post-event SLC image pairs."
    ),
}

# ---------------------------------------------------------------------------
# Background task store  {task_id: InferenceStatus}
# ---------------------------------------------------------------------------
_tasks: dict[str, InferenceStatus] = {}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalise_event_id(event_id: str) -> str:
    """Normalise event_id by replacing hyphens with underscores.

    Allows callers to pass ``"kerala-2018"`` or ``"kerala_2018"``
    interchangeably.
    """
    return event_id.replace("-", "_")


def _module_to_schema(module: DisasterModule) -> DisasterModuleInfo:
    """Convert a ``DisasterModule`` instance to a ``DisasterModuleInfo`` schema.

    Parameters
    ----------
    module : DisasterModule
        Any registered disaster module.

    Returns
    -------
    DisasterModuleInfo
        Pydantic model ready for JSON serialisation.
    """
    info      = module.get_module_info()
    weights   = info["priority_weights"]
    desc      = _MODULE_DESCRIPTIONS.get(info["disaster_type"], "")
    return DisasterModuleInfo(
        disaster_type       = info["disaster_type"],
        display_name        = info["display_name"],
        icon                = info["icon"],
        color               = info["color"],
        status              = info["status"],
        is_live             = info["is_live"],
        demo_event_id       = info["demo_event_id"],
        satellite_sources   = info["satellite_sources"],
        detection_method    = info["detection_method"],
        affected_infra_types= info["affected_infra_types"],
        priority_weights    = PriorityWeights(**weights),
        description         = desc,
    )


def _compute_zone_stats(
    disaster_type: str,
    features: list[dict[str, Any]],
) -> ZoneStats:
    """Compute disaster-specific aggregate statistics from GeoJSON feature properties.

    Each disaster type produces different stat keys:

    Flood
        ``total_flooded_area_km2``, ``avg_confidence``
    Wildfire
        ``total_burned_area_km2``, ``high_severity_pct``
    Landslide
        ``total_slide_area_km2``, ``avg_slope_angle``
    Cyclone
        ``max_wind_speed_kmh``, ``storm_surge_max_m``
    Earthquake
        ``total_damage_area_km2``, ``destroyed_pct``

    Parameters
    ----------
    disaster_type : str
        Module routing key.
    features : list[dict]
        GeoJSON Feature dicts from the ``affected_zones`` FeatureCollection.

    Returns
    -------
    ZoneStats
        Pydantic model with all applicable stats fields populated.
    """
    if not features:
        return ZoneStats(feature_count=0, avg_confidence=0.0)

    props_list: list[dict] = [f.get("properties") or {} for f in features]

    # Universal: confidence
    confidences  = [p["confidence"] for p in props_list if "confidence" in p]
    avg_conf     = round(float(sum(confidences) / len(confidences)), 4) if confidences else 0.0
    n_features   = len(features)

    # ------------------------------------------------------------------ #
    # Flood                                                                #
    # ------------------------------------------------------------------ #
    if disaster_type == "flood":
        total_area = sum(p.get("area_km2", 0.0) for p in props_list)
        return ZoneStats(
            feature_count          = n_features,
            avg_confidence         = avg_conf,
            total_flooded_area_km2 = round(total_area, 2),
        )

    # ------------------------------------------------------------------ #
    # Wildfire                                                             #
    # ------------------------------------------------------------------ #
    if disaster_type == "wildfire":
        total_area  = sum(p.get("area_km2", 0.0) for p in props_list)
        high_count  = sum(1 for p in props_list if p.get("severity") == "high")
        high_pct    = round(100.0 * high_count / n_features, 1) if n_features > 0 else 0.0
        return ZoneStats(
            feature_count         = n_features,
            avg_confidence        = avg_conf,
            total_burned_area_km2 = round(total_area, 2),
            high_severity_pct     = high_pct,
        )

    # ------------------------------------------------------------------ #
    # Landslide                                                            #
    # ------------------------------------------------------------------ #
    if disaster_type == "landslide":
        total_area   = sum(p.get("area_km2", 0.0) for p in props_list)
        slope_angles = [p["slope_angle"] for p in props_list if "slope_angle" in p]
        avg_slope    = round(float(sum(slope_angles) / len(slope_angles)), 1) if slope_angles else 0.0
        return ZoneStats(
            feature_count       = n_features,
            avg_confidence      = avg_conf,
            total_slide_area_km2= round(total_area, 2),
            avg_slope_angle     = avg_slope,
        )

    # ------------------------------------------------------------------ #
    # Cyclone                                                              #
    # ------------------------------------------------------------------ #
    if disaster_type == "cyclone":
        # Surge polygons carry wind_speed_kmh; track LineString has max_wind_speed_kmh
        wind_speeds: list[float] = []
        for p in props_list:
            if "wind_speed_kmh" in p:
                wind_speeds.append(float(p["wind_speed_kmh"]))
            elif "max_wind_speed_kmh" in p:
                wind_speeds.append(float(p["max_wind_speed_kmh"]))

        surges = [float(p["storm_surge_m"]) for p in props_list if "storm_surge_m" in p]

        max_wind   = round(max(wind_speeds), 1) if wind_speeds else 0.0
        max_surge  = round(max(surges), 2)       if surges      else 0.0
        return ZoneStats(
            feature_count    = n_features,
            avg_confidence   = avg_conf,
            max_wind_speed_kmh = max_wind,
            storm_surge_max_m  = max_surge,
        )

    # ------------------------------------------------------------------ #
    # Earthquake                                                           #
    # ------------------------------------------------------------------ #
    if disaster_type == "earthquake":
        total_area    = sum(p.get("area_km2", 0.0) for p in props_list)
        destroyed_cnt = sum(1 for p in props_list if p.get("damage_level") == "destroyed")
        destroyed_pct = round(100.0 * destroyed_cnt / n_features, 1) if n_features > 0 else 0.0
        return ZoneStats(
            feature_count        = n_features,
            avg_confidence       = avg_conf,
            total_damage_area_km2= round(total_area, 2),
            destroyed_pct        = destroyed_pct,
        )

    # Fallback for unknown type
    return ZoneStats(feature_count=n_features, avg_confidence=avg_conf)


def _run_flood_detection_thread(
    task_id:      str,
    event_id:     str,
    bbox:         list[float],
    date_range:   tuple[str, str],
) -> None:
    """Background thread target for live flood detection.

    Updates ``_tasks[task_id]`` at each pipeline stage so callers polling
    ``get_task_status()`` receive live progress.

    Stages and progress milestones
    ------------------------------
    10%  — GEE authentication OK
    30%  — SAR download complete
    60%  — U-Net inference running
    90%  — Post-processing (slope mask, vectorisation)
    100% — Complete

    Parameters
    ----------
    task_id : str
        Key in ``_tasks`` dict to update.
    event_id : str
        Event slug (used as sub-directory name for outputs).
    bbox : list[float]
        ``[min_lon, min_lat, max_lon, max_lat]`` EPSG:4326.
    date_range : tuple[str, str]
        ``(start_date, end_date)`` ISO-8601.
    """

    def _update(status: str, progress: float, message: str, **kwargs: Any) -> None:
        task = _tasks[task_id]
        task.status   = status
        task.progress = progress
        task.message  = message
        for k, v in kwargs.items():
            setattr(task, k, v)

    try:
        _update("running", 5.0, "Initialising flood detection pipeline …")

        module = get_module("flood")

        _update("running", 10.0, "Running Sentinel-1 flood detection …")
        result = module.run_detection(
            event_id   = event_id,
            bbox       = bbox,
            date_range = date_range,
        )

        _update("running", 90.0, "Building detection result …")
        module_info = _module_to_schema(module)
        features    = result["affected_zones"].get("features", [])
        zone_stats  = _compute_zone_stats("flood", features)

        det_result = DetectionResult(
            event_id              = event_id,
            disaster_type         = "flood",
            source                = result.get("source", "unet_inference"),
            affected_zones_geojson= result["affected_zones"],
            stats                 = zone_stats,
            module_info           = module_info,
        )

        _update(
            "complete", 100.0,
            "Flood detection complete.",
            result=det_result.model_dump(),
        )

    except Exception as exc:
        _update(
            "error", 0.0,
            f"Flood detection failed: {exc}",
            error={"error": str(exc), "module": "flood"},
        )


# ===========================================================================
# MLService
# ===========================================================================

class MLService:
    """Central service that bridges the module plugin registry to FastAPI.

    Instantiate once at application startup (or per-test) — all methods are
    stateless with respect to the instance; shared state lives at module level
    in ``_tasks``.

    Example
    -------
    >>> svc = MLService()
    >>> modules = svc.get_available_modules()
    >>> result  = svc.run_detection_demo("kerala_2018", "flood")
    >>> task_id = svc.run_detection_live("kerala_2018", "flood",
    ...               bbox=[76.0, 9.5, 77.5, 11.0],
    ...               date_range=("2018-08-01", "2018-08-20"))
    """

    # ------------------------------------------------------------------ #
    # 1. List modules                                                       #
    # ------------------------------------------------------------------ #

    def get_available_modules(self) -> list[dict[str, Any]]:
        """Return metadata for all 5 registered disaster modules.

        Merges the registry's ``get_module_info()`` output with the
        one-sentence description strings from ``_MODULE_DESCRIPTIONS``.

        Returns
        -------
        list[dict]
            One dict per module in registry order
            (flood → wildfire → landslide → cyclone → earthquake).
            Each dict is the serialised form of ``DisasterModuleInfo``.

        Examples
        --------
        >>> svc = MLService()
        >>> modules = svc.get_available_modules()
        >>> len(modules)
        5
        >>> {m["disaster_type"] for m in modules}
        {'flood', 'wildfire', 'landslide', 'cyclone', 'earthquake'}
        """
        result: list[dict[str, Any]] = []
        for module in DISASTER_MODULES.values():
            schema = _module_to_schema(module)
            result.append(schema.model_dump())
        return result

    # ------------------------------------------------------------------ #
    # 2. Demo detection (sub-200ms, disk read)                            #
    # ------------------------------------------------------------------ #

    def run_detection_demo(
        self,
        event_id:     str,
        disaster_type: str,
    ) -> dict[str, Any]:
        """Load pre-generated demo data and return a full detection result.

        Reads GeoJSON from disk via ``module.get_demo_data()`` and computes
        disaster-specific aggregate statistics in-memory.  No GPU or network
        calls are made.  Target latency: < 200 ms.

        Parameters
        ----------
        event_id : str
            Demo event slug.  Hyphens are normalised to underscores so
            ``"kerala-2018"`` and ``"kerala_2018"`` are equivalent.
        disaster_type : str
            Module routing key (one of the 5 registered types).

        Returns
        -------
        dict
            Serialised ``DetectionResult`` with keys:
            ``event_id``, ``disaster_type``, ``source``,
            ``affected_zones_geojson``, ``stats``, ``module_info``.

        Raises
        ------
        ValueError
            If ``disaster_type`` is not registered.
        FileNotFoundError
            If the demo GeoJSON file does not exist on disk.
        """
        event_id = _normalise_event_id(event_id)
        module   = get_module(disaster_type)   # raises ValueError if unknown

        raw = module.get_demo_data(event_id)   # FileNotFoundError if missing

        features   = raw["affected_zones"].get("features", [])
        zone_stats = _compute_zone_stats(disaster_type, features)
        module_info= _module_to_schema(module)

        result = DetectionResult(
            event_id               = event_id,
            disaster_type          = disaster_type,
            source                 = raw.get("source", "demo"),
            affected_zones_geojson = raw["affected_zones"],
            stats                  = zone_stats,
            module_info            = module_info,
        )
        return result.model_dump()

    # ------------------------------------------------------------------ #
    # 3. Live detection (background thread, returns task_id immediately)   #
    # ------------------------------------------------------------------ #

    def run_detection_live(
        self,
        event_id:      str,
        disaster_type: str,
        bbox:          list[float],
        date_range:    tuple[str, str] | list[str],
    ) -> str:
        """Start a live satellite inference task and return a task_id immediately.

        Only ``FloodModule`` has a working ``run_detection()`` implementation.
        All other modules are set immediately to ``status="error"`` with a
        controlled Phase 2 error message — they never raise an unhandled exception.

        Parameters
        ----------
        event_id : str
            Event slug (also used as the output sub-directory).
        disaster_type : str
            Module routing key.
        bbox : list[float]
            ``[min_lon, min_lat, max_lon, max_lat]`` EPSG:4326.
        date_range : tuple[str, str] or list[str]
            ``(start_date, end_date)`` ISO-8601.

        Returns
        -------
        str
            UUID4 task identifier.  Poll ``get_task_status(task_id)`` for
            progress, or subscribe to ``WS /api/ws/progress``.

        Notes
        -----
        - For non-flood modules the task is set to ``status="error"``
          **synchronously** before this method returns, so the caller can
          immediately read the error from ``get_task_status()`` without waiting.
        - For flood, a ``threading.Thread`` is spawned; the task transitions
          through ``pending → running → complete`` (or ``error``).
        """
        event_id    = _normalise_event_id(event_id)
        task_id     = str(uuid.uuid4())
        date_range  = tuple(date_range)  # normalise list → tuple

        # Validate module exists (ValueError propagates to caller / router)
        get_module(disaster_type)

        # ---------------------------------------------------------------- #
        # Non-flood: controlled Phase 2 error — no thread spawned           #
        # ---------------------------------------------------------------- #
        if disaster_type != "flood":
            _tasks[task_id] = InferenceStatus(
                task_id  = task_id,
                status   = "error",
                progress = 0.0,
                message  = (
                    f"Module '{disaster_type}' is in Phase 2 development. "
                    "Use demo mode (DEMO_MODE=True) for this disaster type."
                ),
                error    = {
                    "error":   "Module in Phase 2 development",
                    "module":  disaster_type,
                    "hint":    "Call run_detection_demo() instead",
                },
            )
            return task_id

        # ---------------------------------------------------------------- #
        # Flood: spawn background thread                                    #
        # ---------------------------------------------------------------- #
        _tasks[task_id] = InferenceStatus(
            task_id  = task_id,
            status   = "pending",
            progress = 0.0,
            message  = "Queued — waiting for GEE and GPU availability.",
        )

        thread = threading.Thread(
            target  = _run_flood_detection_thread,
            args    = (task_id, event_id, bbox, date_range),
            daemon  = True,
            name    = f"flood-inference-{task_id[:8]}",
        )
        thread.start()
        return task_id

    # ------------------------------------------------------------------ #
    # 4. Disaster-specific event stats                                     #
    # ------------------------------------------------------------------ #

    def get_event_stats(
        self,
        event_id:      str,
        disaster_type: str,
    ) -> dict[str, Any]:
        """Compute disaster-specific aggregate statistics for an event.

        Internally calls ``run_detection_demo()`` to load the GeoJSON, then
        extracts the ``stats`` sub-dict.

        Parameters
        ----------
        event_id : str
            Demo event slug.
        disaster_type : str
            Module routing key.

        Returns
        -------
        dict
            A ``ZoneStats``-shaped dict with disaster-specific keys.

        Raises
        ------
        ValueError
            If ``disaster_type`` is not registered.
        FileNotFoundError
            If the demo GeoJSON is missing from disk.
        """
        event_id = _normalise_event_id(event_id)
        result   = self.run_detection_demo(event_id, disaster_type)
        return result["stats"]

    # ------------------------------------------------------------------ #
    # 5. Task status                                                        #
    # ------------------------------------------------------------------ #

    def get_task_status(self, task_id: str) -> dict[str, Any]:
        """Return the current status of a background inference task.

        Parameters
        ----------
        task_id : str
            The UUID returned by ``run_detection_live()``.

        Returns
        -------
        dict
            Serialised ``InferenceStatus`` with keys:
            ``task_id``, ``status``, ``progress``, ``message``,
            ``result`` (when complete), ``error`` (when failed).

        Raises
        ------
        KeyError
            If ``task_id`` is not found in the task store.
        """
        if task_id not in _tasks:
            raise KeyError(f"Task '{task_id}' not found. It may have expired or never existed.")
        return _tasks[task_id].model_dump()

    def list_tasks(self) -> list[dict[str, Any]]:
        """Return status summaries for all tracked inference tasks.

        Useful for an admin dashboard or debugging.  Tasks are never
        evicted from ``_tasks`` during the process lifetime.

        Returns
        -------
        list[dict]
            One ``InferenceStatus`` dict per task, newest-last.
        """
        return [t.model_dump() for t in _tasks.values()]
