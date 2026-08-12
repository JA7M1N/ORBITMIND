"""
OrbitalMind — Narration + Report Router
=========================================
GET  /api/narration/{event_id}/{zone_id}  → LLM-generated zone briefing
POST /api/report/{event_id}               → Full structured incident report
GET  /api/llm/status                      → Ollama availability check

Narration fallback chain
------------------------
  1. DB cache (priority_results.llm_narrative) — < 1 ms
  2. Ollama inference (llama3.2:3b)            — 4–12 s
  3. Pre-written fallback (llm_fallback.py)    — < 1 ms
  4. Generic assembled template                — < 1 ms

The POST /api/report endpoint is consumed by a future PDF generation
service (R4 stage) and by the frontend's "Download Report" button.
"""
from __future__ import annotations

import time
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query

from backend.config import settings
from backend.services import demo_loader
from backend.services.llm_service import LLMService

router  = APIRouter(tags=["Narration"])
_llm    = LLMService()

_PLATFORM_MODULES = [
    {"type": "flood",      "status": "live", "color": "#1e40af"},
    {"type": "wildfire",   "status": "demo", "color": "#dc2626"},
    {"type": "landslide",  "status": "demo", "color": "#92400e"},
    {"type": "cyclone",    "status": "demo", "color": "#7c3aed"},
    {"type": "earthquake", "status": "demo", "color": "#c2410c"},
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_event(event_id: str) -> dict:
    """Load event metadata from manifest; raise 404 if not found."""
    try:
        events = demo_loader.load_all_events()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    norm = event_id.replace("-", "_")
    for ev in events:
        if ev["event_id"].replace("-", "_") == norm:
            return ev
    raise HTTPException(
        status_code=404,
        detail={"error": f"Event '{event_id}' not found",
                "known": [e["event_id"] for e in events]},
    )


def _get_zone(event_id: str, zone_id: str, result: dict) -> dict | None:
    """Find a zone by zone_id (UUID or name match) in a DetectionResult."""
    pz = result.get("priority_zones", [])
    norm = zone_id.replace("-", "_").lower()

    # Try priority_zones list first (fast path, demo data)
    for z in pz:
        zone_name = str(z.get("zone", z.get("zone_name", ""))).lower().replace(" ", "-")
        if zone_name == norm or zone_name.replace("-", "_") == norm:
            return {**z, "event_id": event_id}

    # Try GeoJSON feature properties
    features = result.get("affected_zones_geojson", {}).get("features", [])
    for feat in features:
        props = feat.get("properties", {})
        zone_name = str(props.get("zone_name", props.get("zone", ""))).lower().replace(" ", "-")
        if zone_name == norm or str(props.get("zone_id", "")).lower() == norm:
            return {**props, "event_id": event_id}

    return None


async def _try_db_cache(event_id: str, zone_id: str) -> str | None:
    """Check priority_results.llm_narrative column for a cached narration."""
    try:
        import asyncpg
        dsn = settings.asyncpg_dsn
        conn = await asyncpg.connect(dsn, statement_cache_size=0)
        try:
            row = await conn.fetchrow(
                """
                SELECT llm_narrative FROM priority_results
                WHERE event_id = (
                    SELECT event_id FROM disaster_events
                    WHERE lower(replace(region, ' ', '_')) || '_'
                          || EXTRACT(YEAR FROM date_start)::TEXT = $1
                    LIMIT 1
                )
                AND lower(replace(zone_name, ' ', '-')) = $2
                AND llm_narrative IS NOT NULL
                LIMIT 1
                """,
                event_id.lower().replace("-", "_"),
                zone_id.lower(),
            )
        finally:
            await conn.close()
        if row and row["llm_narrative"]:
            return row["llm_narrative"]
    except Exception:
        pass  # DB not available — skip to Ollama
    return None


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get(
    "/narration/{event_id}/{zone_id}",
    summary="Get LLM narration for a priority zone",
    response_description="3-sentence disaster briefing with recommended action",
    tags=["Narration"],
)
async def get_narration(
    event_id: str,
    zone_id:  str,
    refresh:  bool = Query(
        default=False,
        description="Force regeneration even if cached (skips DB + fallback cache).",
    ),
) -> dict:
    """Generate a 3-sentence AI briefing for a single priority zone.

    **Fallback chain** (< 15 s total):
    1. DB cache (``priority_results.llm_narrative``) — fastest
    2. Ollama ``llama3.2:3b`` — 4–12 s
    3. Pre-written fallback narration (``llm_fallback.py``)
    4. Generic assembled template

    Parameters
    ----------
    event_id : str
        Event slug (e.g. ``kerala-2018`` or ``kerala_2018``).
    zone_id : str
        District name (e.g. ``ernakulam``) or zone UUID.
    refresh : bool
        If True, skip caches and call Ollama directly.

    Returns
    -------
    dict
        ``{zone_id, zone_name, narration, disaster_type, cached, source, model, latency_ms}``
    """
    t0 = time.perf_counter()

    event    = _load_event(event_id)
    dtype    = event["disaster_type"]
    norm_eid = event["event_id"].replace("-", "_")

    # Build DetectionResult to find zone data
    try:
        result = demo_loader.build_detection_result(norm_eid, dtype, event)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    zone_data = _get_zone(norm_eid, zone_id, result)
    if zone_data is None:
        pz_names = [z.get("zone", z.get("zone_name")) for z in result.get("priority_zones", [])]
        raise HTTPException(
            status_code=404,
            detail={
                "error":       f"Zone '{zone_id}' not found in event '{event_id}'",
                "known_zones": pz_names,
            },
        )

    # Attach total_zones for prompt context
    zone_data["total_zones"] = len(result.get("priority_zones", []))
    zone_name = zone_data.get("zone", zone_data.get("zone_name", zone_id))

    # 1. DB cache (skip if refresh=True)
    if not refresh:
        cached_text = await _try_db_cache(norm_eid, zone_id)
        if cached_text:
            return {
                "zone_id":      zone_id,
                "zone_name":    zone_name,
                "narration":    cached_text,
                "disaster_type": dtype,
                "cached":       True,
                "source":       "db_cache",
                "model":        settings.OLLAMA_MODEL,
                "latency_ms":   round((time.perf_counter() - t0) * 1000, 1),
            }

    # 2–4. LLM service with fallback chain
    narration, source = await _llm.generate_narration(zone_data, dtype)

    return {
        "zone_id":       zone_id,
        "zone_name":     zone_name,
        "narration":     narration,
        "disaster_type": dtype,
        "cached":        source == "db_cache",
        "source":        source,
        "model":         settings.OLLAMA_MODEL,
        "latency_ms":    round((time.perf_counter() - t0) * 1000, 1),
    }


@router.post(
    "/report/{event_id}",
    summary="Generate full incident report for an event",
    response_description="Structured incident report with top-5 zone narrations",
    tags=["Narration"],
)
async def generate_report(
    event_id:  str,
    top_n:     int = Query(default=5, ge=1, le=14, description="Number of priority zones to include"),
    narrate:   bool = Query(default=True, description="Include LLM narrations for each zone"),
) -> dict:
    """Build a full structured incident report ready for PDF generation (R4).

    Includes:
    - Event metadata (disaster type, date, region, data source)
    - Module info (satellite, model, resolution)
    - Top-N priority zones with scores + infrastructure counts
    - LLM narrations for each zone (if ``narrate=True``)
    - Aggregate statistics
    - Platform context (other active monitoring modules)
    - Report metadata (generated_at, model, version)

    Parameters
    ----------
    event_id : str
        Event slug.
    top_n : int
        Number of priority zones to include (default 5, max 14).
    narrate : bool
        If False, skips LLM calls — returns report structure with empty narrations.

    Returns
    -------
    dict
        Full report object. Feed to a PDF renderer or return as JSON to frontend.
    """
    t0 = time.perf_counter()

    event    = _load_event(event_id)
    dtype    = event["disaster_type"]
    norm_eid = event["event_id"].replace("-", "_")

    try:
        result = demo_loader.build_detection_result(norm_eid, dtype, event)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    priority_zones: list[dict] = result.get("priority_zones", [])[:top_n]

    # Generate narrations concurrently (all zones at once)
    import asyncio
    zone_reports: list[dict] = []

    if narrate and priority_zones:
        total = len(result.get("priority_zones", []))

        async def _narrate_zone(z: dict) -> dict:
            zd = {**z, "total_zones": total, "event_id": norm_eid}
            narration, source = await _llm.generate_narration(zd, dtype)
            return {
                "rank":              z.get("rank", z.get("priority_rank")),
                "zone_name":         z.get("zone", z.get("zone_name")),
                "priority_score":    z.get("score", z.get("priority_score")),
                "hospitals_affected": z.get("hospitals", z.get("hospitals_affected", 0)),
                "schools_affected":  z.get("schools", z.get("schools_affected", 0)),
                "bridges_affected":  z.get("bridges", z.get("bridges_affected", 0)),
                "population":        z.get("pop", z.get("population", 0)),
                "narration":         narration,
                "narration_source":  source,
            }

        zone_reports = await asyncio.gather(*[_narrate_zone(z) for z in priority_zones])
    else:
        zone_reports = [
            {
                "rank":              z.get("rank"),
                "zone_name":         z.get("zone", z.get("zone_name")),
                "priority_score":    z.get("score"),
                "hospitals_affected": z.get("hospitals", 0),
                "schools_affected":  z.get("schools", 0),
                "bridges_affected":  z.get("bridges", 0),
                "population":        z.get("pop", 0),
                "narration":         None,
                "narration_source":  None,
            }
            for z in priority_zones
        ]

    # Platform context: other active monitoring streams
    platform_context = (
        "OrbitalMind is simultaneously monitoring "
        + " | ".join(
            m["type"].capitalize()
            for m in _PLATFORM_MODULES
            if m["type"] != dtype
        )
        + " events across India."
    )

    report = {
        # ── Report identity ───────────────────────────────────────────────
        "report_id":       f"OM-{norm_eid.upper()}-{int(t0)}",
        "report_version":  settings.API_VERSION,
        "generated_at":    time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "generated_by":    f"OrbitalMind Platform v{settings.API_VERSION}",

        # ── Event ─────────────────────────────────────────────────────────
        "event": {
            "event_id":      norm_eid,
            "disaster_type": dtype,
            "display_name":  event.get("display_name"),
            "region":        event.get("region"),
            "state":         event.get("state"),
            "date_start":    event.get("date_start"),
            "date_end":      event.get("date_end"),
            "status":        event.get("status", "demo"),
            "data_source":   event.get("data_source"),
            "description":   event.get("description"),
        },

        # ── Module info ───────────────────────────────────────────────────
        "module_info":    result.get("module_info", {}),

        # ── Aggregate stats ───────────────────────────────────────────────
        "aggregate_stats": result.get("stats", {}),

        # ── Priority zones with narrations ────────────────────────────────
        "priority_zones": zone_reports,

        # ── Platform context ──────────────────────────────────────────────
        "platform_context": platform_context,
        "active_modules":   _PLATFORM_MODULES,

        # ── Report metadata ───────────────────────────────────────────────
        "llm_model":      settings.OLLAMA_MODEL,
        "demo_mode":      settings.DEMO_MODE,
        "latency_ms":     round((time.perf_counter() - t0) * 1000, 1),
    }

    return report


@router.get(
    "/llm/status",
    summary="Check Ollama LLM availability",
    response_description="Ollama status and available models",
    tags=["Narration"],
)
async def llm_status() -> dict:
    """Check if Ollama is running and the configured model is available.

    Returns
    -------
    dict
        ``{available, model, models, error}``
        If ``available=False``, ``error`` contains the fix command.
    """
    return await _llm.check_availability()
