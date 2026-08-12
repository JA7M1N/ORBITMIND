"""
OrbitalMind — Events Router v2
================================
GET /api/events                     -> list all events (manifest or DB)
GET /api/events?disaster_type=flood -> filtered list
GET /api/events/{event_id}          -> single event metadata
GET /api/events/{event_id}/zones    -> full DetectionResult (GeoJSON + priority)
GET /api/events/{event_id}/stats    -> aggregate stats dict only

DEMO_MODE=True  (default): reads from events_manifest.json + demo_loader
DEMO_MODE=False:            queries disaster_events DB via GIS service
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from backend.config import settings
from backend.services import demo_loader

router = APIRouter(prefix="/events", tags=["Events"])

_VALID_TYPES = frozenset(settings.SUPPORTED_DISASTERS)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _find_event(event_id: str, events: list[dict]) -> dict:
    """Look up event by slug (normalised: - → _)."""
    norm = event_id.replace("-", "_")
    for ev in events:
        if ev["event_id"] == norm or ev["event_id"].replace("-", "_") == norm:
            return ev
    raise HTTPException(
        status_code=404,
        detail={
            "error":    f"Event '{event_id}' not found",
            "known_ids": [e["event_id"] for e in events],
        },
    )


def _load_events() -> list[dict]:
    """Load events — manifest in DEMO_MODE, DB otherwise."""
    try:
        return demo_loader.load_all_events()
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"events_manifest.json missing: {exc}. "
                   "Run: python scripts/generate_mock_data.py",
        )


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get(
    "",
    summary="List all demo events",
    response_description="All disaster events from manifest or DB",
)
async def list_events(
    disaster_type: Optional[str] = Query(
        default=None,
        description="Filter by disaster type (flood | wildfire | landslide | cyclone | earthquake)",
    )
) -> list[dict]:
    """Return all events, optionally filtered by ``disaster_type``.

    In ``DEMO_MODE=True`` reads from ``events_manifest.json``.
    In ``DEMO_MODE=False`` would query the ``disaster_events`` PostgreSQL table.

    Used by the frontend ``EventSelector`` dropdown and module nav tabs.
    """
    if disaster_type and disaster_type not in _VALID_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid disaster_type '{disaster_type}'. "
                   f"Valid: {sorted(_VALID_TYPES)}",
        )

    events = _load_events()

    if disaster_type:
        events = [e for e in events if e.get("disaster_type") == disaster_type]

    return events


@router.get(
    "/{event_id}",
    summary="Get single event metadata",
    response_description="Full event metadata record",
)
async def get_event(event_id: str) -> dict:
    """Return metadata for a single event by slug or UUID.

    Parameters
    ----------
    event_id : str
        Event slug — e.g. ``kerala_2018`` or ``kerala-2018`` (normalised).

    Raises
    ------
    404
        If event not found.
    """
    events = _load_events()
    return _find_event(event_id, events)


@router.get(
    "/{event_id}/zones",
    summary="Get affected-zone GeoJSON + priority scores",
    response_description="Full DetectionResult: GeoJSON FeatureCollection with priority metadata",
)
async def get_event_zones(event_id: str) -> dict:
    """Return the full ``DetectionResult`` for an event.

    **DEMO_MODE=True** (default):
    Loads GeoJSON from disk via ``demo_loader``, attaches hardcoded priority
    data (Census 2011 / HMIS sources), returns in < 50 ms.

    **DEMO_MODE=False**:
    Queries PostGIS via ``GISService.get_event_zones_geojson()`` — requires
    active DB connection and PostGIS extension.

    Response includes:
    - ``affected_zones_geojson`` — GeoJSON FeatureCollection sorted by priority_score desc
    - ``priority_zones``         — ranked district list with hospital/school/bridge counts
    - ``stats``                  — disaster-specific aggregate statistics
    - ``module_info``            — ML model and satellite source details

    Parameters
    ----------
    event_id : str
        Event slug.
    """
    events = _load_events()
    event  = _find_event(event_id, events)
    norm   = event["event_id"].replace("-", "_")
    dtype  = event["disaster_type"]

    if settings.DEMO_MODE:
        # ── Fast demo path ────────────────────────────────────────────────
        try:
            return demo_loader.build_detection_result(norm, dtype, event)
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=503,
                detail=f"Demo GeoJSON missing: {exc}. "
                       "Run: python scripts/generate_mock_data.py --force",
            )
    else:
        # ── Live DB path via GIS service ──────────────────────────────────
        try:
            from backend.services.gis_service import GISService
            svc = GISService()
            await svc.connect()
            try:
                fc       = await svc.get_event_zones_geojson(norm)
                priority = await svc.get_priority_zones(norm, dtype)
            finally:
                await svc.disconnect()

            return {
                "event_id":               norm,
                "disaster_type":          dtype,
                "display_name":           event.get("display_name", norm),
                "region":                 event.get("region", ""),
                "date":                   event.get("date_start", ""),
                "status":                 "live",
                "module_info":            demo_loader._MODULE_INFO.get(dtype, {}),
                "affected_zones_geojson": fc,
                "priority_zones":         priority,
                "stats":                  {"zone_count": len(fc.get("features", []))},
            }
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail=f"DB/GIS error: {exc}. "
                       "Check DEMO_MODE=True in .env if PostGIS not yet installed.",
            )


@router.get(
    "/{event_id}/stats",
    summary="Get disaster-specific aggregate statistics",
    response_description="Stats dict with disaster-type-specific keys",
)
async def get_event_stats(event_id: str) -> dict:
    """Return only the ``stats`` portion of a DetectionResult.

    Disaster-specific keys:
    - **flood**:      total_flooded_area_km2, avg_confidence, people_affected
    - **wildfire**:   total_burned_area_km2, high_severity_pct, fire_perimeter_km
    - **landslide**:  total_slide_area_km2, avg_slope_angle_deg, roads_blocked
    - **cyclone**:    max_wind_speed_kmh, storm_surge_max_m, cyclone_category
    - **earthquake**: total_damage_area_km2, max_pga_g, magnitude, depth_km

    Parameters
    ----------
    event_id : str
        Event slug.
    """
    events = _load_events()
    event  = _find_event(event_id, events)
    norm   = event["event_id"].replace("-", "_")
    dtype  = event["disaster_type"]

    try:
        result = demo_loader.build_detection_result(norm, dtype, event)
        return result["stats"]
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
