"""
OrbitalMind — Platform Summary Router
========================================
GET /api/platform/summary

Returns an aggregate view across all 5 disaster modules.
DEMO_MODE=True: hardcoded realistic data (no DB required, < 5 ms).
DEMO_MODE=False: queries disaster_events + priority_results from PostGIS.

Used by the frontend dashboard hero cards and the report platform-context block.
"""
from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, HTTPException

from backend.config import settings
from backend.services import demo_loader

router = APIRouter(prefix="/platform", tags=["Platform"])


# ── Hardcoded demo summary (Census 2011 + HMIS + event records) ───────────────

_DEMO_SUMMARY: dict[str, Any] = {
    "total_modules":        5,
    "live_modules":         1,        # FloodModule Phase 1
    "demo_modules":         4,
    "total_events_tracked": 5,
    "last_updated":         "2024-08-08T18:00:00Z",
    "platform_version":     "2.0.0",

    "disasters_covered": [
        "flood", "wildfire", "landslide", "cyclone", "earthquake"
    ],

    "per_disaster": {
        "flood": {
            "events":          1,
            "module_status":   "live",
            "color":           "#1e40af",
            "icon":            "droplets",
            "satellite":       "Sentinel-1 SAR",
            "pop_affected":    14_744_452,     # sum of top-8 Kerala districts
            "area_km2":        5_210,
            "zones_scored":    14,
            "top_region":      "Kerala",
            "top_event":       "kerala_2018",
            "top_event_name":  "Kerala Floods 2018",
            "top_zone":        "Ernakulam",
            "top_score":       0.87,
            "avg_confidence":  0.74,
            "date_latest":     "2018-08-01",
        },
        "wildfire": {
            "events":          1,
            "module_status":   "demo",
            "color":           "#dc2626",
            "icon":            "flame",
            "satellite":       "Sentinel-2 SWIR",
            "pop_affected":    2_261_189,      # Chamoli + Rudraprayag + Uttarkashi
            "area_km2":        1_840,
            "zones_scored":    5,
            "top_region":      "Uttarakhand",
            "top_event":       "uttarakhand_2024",
            "top_event_name":  "Uttarakhand Forest Fire 2024",
            "top_zone":        "Chamoli",
            "top_score":       0.81,
            "avg_confidence":  0.71,
            "date_latest":     "2024-05-15",
        },
        "landslide": {
            "events":          1,
            "module_status":   "demo",
            "color":           "#92400e",
            "icon":            "mountain",
            "satellite":       "Sentinel-1 InSAR + SRTM",
            "pop_affected":    3_158_648,      # Shimla + Kullu + Mandi
            "area_km2":        890,
            "zones_scored":    6,
            "top_region":      "Himachal Pradesh",
            "top_event":       "himachal_2023",
            "top_event_name":  "Himachal Pradesh Landslides 2023",
            "top_zone":        "Shimla",
            "top_score":       0.79,
            "avg_confidence":  0.68,
            "date_latest":     "2023-07-09",
        },
        "cyclone": {
            "events":          1,
            "module_status":   "demo",
            "color":           "#7c3aed",
            "icon":            "wind",
            "satellite":       "INSAT-3D IR+WV",
            "pop_affected":    11_983_666,     # all 5 coastal Odisha districts
            "area_km2":        4_120,
            "zones_scored":    5,
            "top_region":      "Odisha",
            "top_event":       "odisha_2023",
            "top_event_name":  "Cyclone Biparjoy 2023",
            "top_zone":        "Srikakulam",
            "top_score":       0.83,
            "avg_confidence":  0.76,
            "date_latest":     "2023-06-15",
        },
        "earthquake": {
            "events":          1,
            "module_status":   "demo",
            "color":           "#c2410c",
            "icon":            "activity",
            "satellite":       "Sentinel-1 D-InSAR",
            "pop_affected":    11_432_801,     # Kutch + Rajkot + Jamnagar + Morbi
            "area_km2":        3_670,
            "zones_scored":    7,
            "top_region":      "Gujarat",
            "top_event":       "gujarat_2024",
            "top_event_name":  "Gujarat Earthquake 2024",
            "top_zone":        "Kutch",
            "top_score":       0.84,
            "avg_confidence":  0.69,
            "date_latest":     "2024-01-16",
        },
    },

    "totals": {
        "total_pop_affected":  43_580_556,
        "total_area_km2":      15_730,
        "total_zones_scored":  37,
        "avg_priority_score":  0.73,
    },
}


# ── Route ─────────────────────────────────────────────────────────────────────

@router.get(
    "/summary",
    summary="Platform-wide aggregate summary across all 5 disaster modules",
    response_description="Summary statistics for dashboard hero cards",
)
async def platform_summary() -> dict:
    """Return aggregate statistics across all 5 OrbitalMind disaster modules.

    **DEMO_MODE=True** (default):
    Returns hardcoded realistic data in < 5 ms. No DB required.

    **DEMO_MODE=False**:
    Queries ``disaster_events``, ``priority_results``, and ``admin_zones``
    via PostGIS. Falls back to demo data if DB is unavailable.

    Returns
    -------
    dict
        ``total_modules``, ``live_modules``, ``demo_modules``,
        ``total_events_tracked``, ``disasters_covered``,
        ``per_disaster`` (one entry per type with top zone + stats),
        ``totals`` (platform-wide aggregates).
    """
    t0 = time.perf_counter()

    if settings.DEMO_MODE:
        result = dict(_DEMO_SUMMARY)
        result["latency_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        result["source"]     = "demo_hardcoded"
        return result

    # ── Live DB path ──────────────────────────────────────────────────────
    try:
        import asyncpg
        pool = await asyncpg.create_pool(
            settings.asyncpg_dsn,
            statement_cache_size=0,
            min_size=1, max_size=2,
        )
        async with pool.acquire() as conn:
            ev_rows = await conn.fetch(
                """
                SELECT disaster_type,
                       COUNT(*)                       AS events,
                       MAX(date_start)                AS latest
                FROM disaster_events
                GROUP BY disaster_type
                """
            )
            pr_rows = await conn.fetch(
                """
                SELECT pr.disaster_type,
                       COUNT(DISTINCT pr.result_id)::INT   AS zones,
                       COALESCE(SUM(adm.population), 0)    AS pop,
                       MAX(pr.priority_score)              AS top_score,
                       (SELECT zone_name FROM priority_results p2
                        WHERE p2.event_id = pr.event_id
                          AND p2.priority_rank = 1 LIMIT 1) AS top_zone
                FROM priority_results pr
                LEFT JOIN admin_zones adm ON pr.admin_zone_id = adm.zone_id
                GROUP BY pr.disaster_type, pr.event_id
                """
            )
        await pool.close()

        ev_map = {r["disaster_type"]: dict(r) for r in ev_rows}
        pr_map = {r["disaster_type"]: dict(r) for r in pr_rows}

        per_disaster: dict[str, Any] = {}
        for dtype in settings.SUPPORTED_DISASTERS:
            demo = _DEMO_SUMMARY["per_disaster"].get(dtype, {})
            ev   = ev_map.get(dtype, {})
            pr   = pr_map.get(dtype, {})
            per_disaster[dtype] = {
                **demo,
                "events":        int(ev.get("events", demo.get("events", 0))),
                "zones_scored":  int(pr.get("zones", demo.get("zones_scored", 0))),
                "pop_affected":  int(pr.get("pop", demo.get("pop_affected", 0))),
                "top_score":     float(pr.get("top_score") or demo.get("top_score", 0)),
                "top_zone":      pr.get("top_zone") or demo.get("top_zone"),
                "date_latest":   str(ev.get("latest") or demo.get("date_latest", "")),
            }

        total_pop  = sum(v.get("pop_affected", 0) for v in per_disaster.values())
        total_area = sum(v.get("area_km2", 0) for v in per_disaster.values())
        total_zones= sum(v.get("zones_scored", 0) for v in per_disaster.values())

        return {
            **_DEMO_SUMMARY,
            "per_disaster": per_disaster,
            "totals": {
                "total_pop_affected": total_pop,
                "total_area_km2":     total_area,
                "total_zones_scored": total_zones,
            },
            "source":     "database",
            "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
        }

    except Exception as exc:
        # DB failed — return demo data with warning
        result = dict(_DEMO_SUMMARY)
        result["source"]     = "demo_fallback"
        result["db_error"]   = str(exc) if settings.DEMO_MODE else "Database connection unavailable."
        result["latency_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        return result
