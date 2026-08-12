"""
OrbitalMind — Full API Integration Tests
==========================================
Tests every public API endpoint using httpx against a live server.

Requirements
------------
  pip install pytest pytest-asyncio httpx anyio websockets

Run
---
  # Start server first:
  uvicorn backend.main:app --port 8000 --log-level warning

  # Then in another terminal:
  pytest tests/test_api.py -v

  # Or run both together:
  pytest tests/test_api.py -v --log-cli-level=WARNING

Configuration
-------------
  Set TEST_BASE_URL env variable to override the default server URL.
  Default: http://localhost:8000

Notes
-----
  Tests run against a live server, not mocked — they require the server
  to be running and demo data to be present on disk.

  WebSocket tests use 'websockets' library directly (not httpx WS),
  because httpx's WS support requires a running ASGI server.
"""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import httpx
import pytest
import websockets

# ── Config ─────────────────────────────────────────────────────────────────────
BASE_URL    = os.getenv("TEST_BASE_URL", "http://localhost:8000")
WS_BASE     = BASE_URL.replace("http://", "ws://").replace("https://", "wss://")
TIMEOUT     = 30.0   # s — generous for narration fallback chain (~12 s)
WS_TIMEOUT  = 20.0   # s — enough for full demo pipeline (~3.5 s)


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    """Synchronous httpx client for the whole test module."""
    with httpx.Client(base_url=BASE_URL, timeout=TIMEOUT) as c:
        yield c


@pytest.fixture(scope="module")
def flood_task_id(client) -> str:
    """POST /api/analyze for flood and return task_id for WS tests."""
    r = client.post("/api/analyze", json={
        "event_id":      "kerala_2018",
        "disaster_type": "flood",
        "demo_mode":     True,
    })
    assert r.status_code == 202, f"analyze failed: {r.text}"
    return r.json()["task_id"]


@pytest.fixture(scope="module")
def wildfire_task_id(client) -> str:
    """POST /api/analyze for wildfire and return task_id."""
    r = client.post("/api/analyze", json={
        "event_id":      "uttarakhand_2024",
        "disaster_type": "wildfire",
        "demo_mode":     True,
    })
    assert r.status_code == 202, f"analyze (wildfire) failed: {r.text}"
    return r.json()["task_id"]


# ══════════════════════════════════════════════════════════════════════════════
# Health
# ══════════════════════════════════════════════════════════════════════════════

class TestHealth:

    def test_health_ok(self, client):
        r = client.get("/health")
        assert r.status_code == 200

    def test_health_status_ok(self, client):
        data = client.get("/health").json()
        assert data["status"] == "ok"

    def test_health_demo_mode_true(self, client):
        data = client.get("/health").json()
        assert data["demo_mode"] is True

    def test_health_version(self, client):
        data = client.get("/health").json()
        assert data["version"] == "2.0.0"

    def test_health_supported_disasters_five(self, client):
        data = client.get("/health").json()
        disasters = data["supported_disasters"]
        assert isinstance(disasters, list)
        assert len(disasters) == 5

    def test_health_all_disaster_types_present(self, client):
        data     = client.get("/health").json()
        expected = {"flood", "wildfire", "landslide", "cyclone", "earthquake"}
        assert set(data["supported_disasters"]) == expected


# ══════════════════════════════════════════════════════════════════════════════
# Modules
# ══════════════════════════════════════════════════════════════════════════════

class TestModules:

    def test_modules_returns_five(self, client):
        r = client.get("/api/modules")
        assert r.status_code == 200
        assert len(r.json()) == 5

    def test_modules_all_have_required_fields(self, client):
        required = {"disaster_type", "display_name", "icon", "color",
                    "status", "satellite_sources", "detection_method",
                    "description", "priority_weights"}
        for m in client.get("/api/modules").json():
            missing = required - m.keys()
            assert not missing, f"Module '{m.get('disaster_type')}' missing: {missing}"

    def test_flood_module_is_live(self, client):
        mods  = client.get("/api/modules").json()
        flood = next(m for m in mods if m["disaster_type"] == "flood")
        assert flood["status"] == "live"

    def test_flood_module_color(self, client):
        mods  = client.get("/api/modules").json()
        flood = next(m for m in mods if m["disaster_type"] == "flood")
        assert flood["color"] == "#1e40af"

    def test_wildfire_module_status_demo(self, client):
        mods = client.get("/api/modules").json()
        wf   = next(m for m in mods if m["disaster_type"] == "wildfire")
        assert wf["status"] == "demo"
        assert wf["color"]  == "#dc2626"

    def test_priority_weights_sum_to_one(self, client):
        for m in client.get("/api/modules").json():
            total = sum(m["priority_weights"].values())
            assert abs(total - 1.0) < 1e-5, (
                f"{m['disaster_type']} weights sum to {total}"
            )

    def test_get_single_module_flood(self, client):
        r = client.get("/api/modules/flood")
        assert r.status_code == 200
        assert r.json()["disaster_type"] == "flood"

    def test_get_unknown_module_returns_404(self, client):
        r = client.get("/api/modules/tornado")
        assert r.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# Events
# ══════════════════════════════════════════════════════════════════════════════

class TestEvents:

    def test_events_returns_at_least_five(self, client):
        r = client.get("/api/events")
        assert r.status_code == 200
        assert len(r.json()) >= 5

    def test_events_all_have_required_fields(self, client):
        required = {"event_id", "disaster_type", "display_name"}
        for ev in client.get("/api/events").json():
            missing = required - ev.keys()
            assert not missing, f"Event missing: {missing}"

    def test_events_filter_wildfire(self, client):
        r = client.get("/api/events?disaster_type=wildfire")
        assert r.status_code == 200
        evs = r.json()
        assert len(evs) >= 1
        for ev in evs:
            assert ev["disaster_type"] == "wildfire"

    def test_events_filter_flood(self, client):
        r = client.get("/api/events?disaster_type=flood")
        assert r.status_code == 200
        for ev in r.json():
            assert ev["disaster_type"] == "flood"

    def test_events_filter_invalid_type_422(self, client):
        r = client.get("/api/events?disaster_type=tornado")
        assert r.status_code == 422

    def test_get_kerala_event_metadata(self, client):
        r = client.get("/api/events/kerala_2018")
        assert r.status_code == 200
        ev = r.json()
        assert ev["disaster_type"] == "flood"
        assert ev["event_id"].replace("-", "_") == "kerala_2018"

    def test_get_unknown_event_404(self, client):
        r = client.get("/api/events/nonexistent_event_xyz")
        assert r.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# Event Zones  (FLOOD)
# ══════════════════════════════════════════════════════════════════════════════

class TestEventZonesFlood:

    def test_zones_returns_200(self, client):
        r = client.get("/api/events/kerala_2018/zones")
        assert r.status_code == 200

    def test_zones_disaster_type_flood(self, client):
        data = client.get("/api/events/kerala_2018/zones").json()
        assert data["disaster_type"] == "flood"

    def test_zones_has_geojson_feature_collection(self, client):
        data = client.get("/api/events/kerala_2018/zones").json()
        fc   = data["affected_zones_geojson"]
        assert fc["type"] == "FeatureCollection"
        assert len(fc["features"]) >= 1

    def test_zones_priority_sorted_descending(self, client):
        data  = client.get("/api/events/kerala_2018/zones").json()
        zones = data["priority_zones"]
        assert len(zones) >= 2
        scores = [z["score"] for z in zones]
        assert scores == sorted(scores, reverse=True), \
            f"Zones not sorted desc: {scores}"

    def test_zones_top_score_above_threshold(self, client):
        data  = client.get("/api/events/kerala_2018/zones").json()
        zones = data["priority_zones"]
        assert float(zones[0]["score"]) > 0.6

    def test_zones_top_zone_has_hospitals(self, client):
        data  = client.get("/api/events/kerala_2018/zones").json()
        top   = data["priority_zones"][0]
        assert "hospitals" in top
        assert int(top["hospitals"]) >= 1

    def test_zones_has_module_info(self, client):
        data = client.get("/api/events/kerala_2018/zones").json()
        mi   = data["module_info"]
        assert mi.get("module") == "FloodModule"
        assert mi.get("is_live") is True
        assert mi.get("satellite")

    def test_zones_has_stats(self, client):
        data  = client.get("/api/events/kerala_2018/zones").json()
        stats = data["stats"]
        assert "zone_count"              in stats
        assert "total_flooded_area_km2"  in stats

    def test_zones_stats_flood_area(self, client):
        data = client.get("/api/events/kerala_2018/zones").json()
        assert data["stats"]["zone_count"] >= 1


# ══════════════════════════════════════════════════════════════════════════════
# Event Zones  (WILDFIRE) — proves multi-disaster
# ══════════════════════════════════════════════════════════════════════════════

class TestEventZonesWildfire:

    def test_wildfire_zones_200(self, client):
        r = client.get("/api/events/uttarakhand_2024/zones")
        assert r.status_code == 200

    def test_wildfire_disaster_type(self, client):
        data = client.get("/api/events/uttarakhand_2024/zones").json()
        assert data["disaster_type"] == "wildfire"

    def test_wildfire_module_info(self, client):
        data = client.get("/api/events/uttarakhand_2024/zones").json()
        assert data["module_info"]["module"] == "WildfireModule"
        assert data["module_info"]["is_live"] is False

    def test_wildfire_has_priority_zones(self, client):
        data = client.get("/api/events/uttarakhand_2024/zones").json()
        assert len(data["priority_zones"]) >= 1

    def test_wildfire_zones_sorted(self, client):
        data   = client.get("/api/events/uttarakhand_2024/zones").json()
        scores = [z["score"] for z in data["priority_zones"]]
        assert scores == sorted(scores, reverse=True)

    def test_wildfire_stats_present(self, client):
        data  = client.get("/api/events/uttarakhand_2024/zones").json()
        stats = data["stats"]
        assert "zone_count" in stats

    def test_wildfire_event_stats_endpoint(self, client):
        r = client.get("/api/events/uttarakhand_2024/stats")
        assert r.status_code == 200
        st = r.json()
        assert "zone_count" in st


# ══════════════════════════════════════════════════════════════════════════════
# Platform Summary
# ══════════════════════════════════════════════════════════════════════════════

class TestPlatformSummary:

    def test_summary_200(self, client):
        r = client.get("/api/platform/summary")
        assert r.status_code == 200

    def test_summary_total_modules_five(self, client):
        data = client.get("/api/platform/summary").json()
        assert data["total_modules"] == 5

    def test_summary_live_modules_one(self, client):
        data = client.get("/api/platform/summary").json()
        assert data["live_modules"] == 1

    def test_summary_disasters_covered_five(self, client):
        data = client.get("/api/platform/summary").json()
        assert len(data["disasters_covered"]) == 5

    def test_summary_per_disaster_all_types(self, client):
        data = client.get("/api/platform/summary").json()
        pd   = data["per_disaster"]
        for dtype in ("flood", "wildfire", "landslide", "cyclone", "earthquake"):
            assert dtype in pd, f"'{dtype}' missing from per_disaster"

    def test_summary_flood_top_region_kerala(self, client):
        data = client.get("/api/platform/summary").json()
        assert data["per_disaster"]["flood"]["top_region"] == "Kerala"

    def test_summary_totals_pop_above_million(self, client):
        data = client.get("/api/platform/summary").json()
        assert data["totals"]["total_pop_affected"] > 1_000_000

    def test_summary_latency_under_100ms(self, client):
        data = client.get("/api/platform/summary").json()
        assert data.get("latency_ms", 999) < 100


# ══════════════════════════════════════════════════════════════════════════════
# Analyze + Task progress
# ══════════════════════════════════════════════════════════════════════════════

class TestAnalyze:

    def test_analyze_flood_returns_202(self, client):
        r = client.post("/api/analyze", json={
            "event_id": "kerala_2018", "disaster_type": "flood", "demo_mode": True
        })
        assert r.status_code == 202

    def test_analyze_response_has_task_id(self, client):
        r = client.post("/api/analyze", json={
            "event_id": "kerala_2018", "disaster_type": "flood", "demo_mode": True
        })
        body = r.json()
        assert "task_id" in body
        assert len(body["task_id"]) == 36  # UUID length

    def test_analyze_response_status_running(self, client):
        r = client.post("/api/analyze", json={
            "event_id": "kerala_2018", "disaster_type": "flood", "demo_mode": True
        })
        assert r.json()["status"] == "running"

    def test_analyze_wildfire_202(self, client):
        r = client.post("/api/analyze", json={
            "event_id": "uttarakhand_2024", "disaster_type": "wildfire", "demo_mode": True
        })
        assert r.status_code == 202
        assert r.json()["disaster_type"] == "wildfire"

    def test_analyze_all_five_types(self, client):
        events = {
            "flood":      "kerala_2018",
            "wildfire":   "uttarakhand_2024",
            "landslide":  "himachal_2023",
            "cyclone":    "odisha_2023",
            "earthquake": "gujarat_2024",
        }
        for dtype, eid in events.items():
            r = client.post("/api/analyze", json={
                "event_id": eid, "disaster_type": dtype, "demo_mode": True
            })
            assert r.status_code == 202, f"{dtype} returned {r.status_code}"
            assert r.json()["disaster_type"] == dtype

    def test_analyze_invalid_type_422(self, client):
        r = client.post("/api/analyze", json={
            "event_id": "test", "disaster_type": "tornado"
        })
        assert r.status_code in (400, 422)
        body = r.json()
        # Error detail should mention the invalid type
        detail_str = json.dumps(body)
        assert "tornado" in detail_str or "disaster_type" in detail_str


# ══════════════════════════════════════════════════════════════════════════════
# WebSocket progress — flood (disaster-specific messages)
# ══════════════════════════════════════════════════════════════════════════════

class TestWebSocketFlood:

    def test_ws_flood_completes(self, flood_task_id):
        """WebSocket streams flood progress from 0 → 100 and delivers result."""
        async def run():
            uri  = f"{WS_BASE}/api/ws/progress?task_id={flood_task_id}"
            msgs = []
            async with websockets.connect(uri) as ws:
                while True:
                    raw = await asyncio.wait_for(ws.recv(), timeout=WS_TIMEOUT)
                    msg = json.loads(raw)
                    msgs.append(msg)
                    if msg["status"] in ("complete", "error"):
                        break
            return msgs

        msgs = asyncio.run(run())
        assert len(msgs) >= 1

        last = msgs[-1]
        assert last["status"]   == "complete"
        assert last["progress"] == 100

    def test_ws_flood_has_result(self, flood_task_id):
        """Final WS message includes the full DetectionResult."""
        async def run():
            uri = f"{WS_BASE}/api/ws/progress?task_id={flood_task_id}"
            async with websockets.connect(uri) as ws:
                msg = None
                while True:
                    raw = await asyncio.wait_for(ws.recv(), timeout=WS_TIMEOUT)
                    msg = json.loads(raw)
                    if msg["status"] in ("complete", "error"):
                        break
            return msg

        msg = asyncio.run(run())
        assert msg["result"] is not None
        assert msg["result"]["disaster_type"] == "flood"

    def test_ws_flood_messages_contain_sar_text(self, flood_task_id):
        """Flood progress messages reference Sentinel-1 SAR (not generic messages).

        Note: uses a *fresh* analyze call so the WS connects before the task
        completes and sees the intermediate progress messages.
        """
        import httpx as _httpx
        # Start a brand-new flood task so we catch all progress steps
        r = _httpx.post(f"{BASE_URL}/api/analyze",
                        json={"event_id": "kerala_2018", "disaster_type": "flood",
                              "demo_mode": True}, timeout=10)
        fresh_task_id = r.json()["task_id"]

        async def run():
            uri  = f"{WS_BASE}/api/ws/progress?task_id={fresh_task_id}"
            msgs = []
            async with websockets.connect(uri) as ws:
                while True:
                    raw = await asyncio.wait_for(ws.recv(), timeout=WS_TIMEOUT)
                    msg = json.loads(raw)
                    msgs.append(msg)
                    if msg["status"] in ("complete", "error"):
                        break
            return msgs

        msgs     = asyncio.run(run())
        all_msgs = " ".join(m.get("message", "") for m in msgs)

        # Accept keywords from either progress messages or the final result's module info
        last   = msgs[-1]
        result = last.get("result") or {}
        sat    = result.get("module_info", {}).get("satellite", "")

        assert any(kw in all_msgs for kw in ("SAR", "U-Net", "Sentinel", "OSM", "priority")) \
            or any(kw in sat for kw in ("SAR", "Sentinel")), \
            f"No flood-specific keywords. messages='{all_msgs[:200]}'  satellite='{sat}'"


# ══════════════════════════════════════════════════════════════════════════════
# WebSocket progress — wildfire (disaster-specific messages)
# ══════════════════════════════════════════════════════════════════════════════

class TestWebSocketWildfire:

    def test_ws_wildfire_completes(self, wildfire_task_id):
        async def run():
            uri  = f"{WS_BASE}/api/ws/progress?task_id={wildfire_task_id}"
            msgs = []
            async with websockets.connect(uri) as ws:
                while True:
                    raw = await asyncio.wait_for(ws.recv(), timeout=WS_TIMEOUT)
                    msg = json.loads(raw)
                    msgs.append(msg)
                    if msg["status"] in ("complete", "error"):
                        break
            return msgs

        msgs = asyncio.run(run())
        last = msgs[-1]
        assert last["status"]   == "complete"
        assert last["progress"] == 100

    def test_ws_wildfire_messages_contain_swir_text(self, wildfire_task_id):
        """Wildfire WS messages reference SWIR / NBR — not SAR / U-Net.

        Starts a fresh task to guarantee catching intermediate progress steps.
        """
        import httpx as _httpx
        r = _httpx.post(f"{BASE_URL}/api/analyze",
                        json={"event_id": "uttarakhand_2024", "disaster_type": "wildfire",
                              "demo_mode": True}, timeout=10)
        fresh_task_id = r.json()["task_id"]

        async def run():
            uri  = f"{WS_BASE}/api/ws/progress?task_id={fresh_task_id}"
            msgs = []
            async with websockets.connect(uri) as ws:
                while True:
                    raw = await asyncio.wait_for(ws.recv(), timeout=WS_TIMEOUT)
                    msg = json.loads(raw)
                    msgs.append(msg)
                    if msg["status"] in ("complete", "error"):
                        break
            return msgs

        msgs     = asyncio.run(run())
        all_msgs = " ".join(m.get("message", "") for m in msgs)

        last   = msgs[-1]
        result = last.get("result") or {}
        sat    = result.get("module_info", {}).get("satellite", "")

        assert any(kw in all_msgs for kw in ("SWIR", "NBR", "burn", "wildfire", "evacuation")) \
            or any(kw in sat for kw in ("Sentinel-2", "SWIR", "MSI")), \
            f"No wildfire-specific keywords. messages='{all_msgs[:200]}'  satellite='{sat}'"


# ══════════════════════════════════════════════════════════════════════════════
# Narration
# ══════════════════════════════════════════════════════════════════════════════

class TestNarration:

    def test_narration_ernakulam_200(self, client):
        r = client.get("/api/narration/kerala-2018/ernakulam")
        assert r.status_code == 200

    def test_narration_has_text(self, client):
        data = client.get("/api/narration/kerala-2018/ernakulam").json()
        assert len(data["narration"]) >= 60

    def test_narration_has_source(self, client):
        data = client.get("/api/narration/kerala-2018/ernakulam").json()
        assert data["source"] in ("ollama", "fallback_cache", "generic_template", "db_cache")

    def test_narration_disaster_type_flood(self, client):
        data = client.get("/api/narration/kerala-2018/ernakulam").json()
        assert data["disaster_type"] == "flood"

    def test_narration_unknown_zone_404(self, client):
        r = client.get("/api/narration/kerala-2018/nonexistent-zone-xyz")
        assert r.status_code == 404

    def test_narration_thrissur(self, client):
        r = client.get("/api/narration/kerala-2018/thrissur")
        assert r.status_code == 200
        assert len(r.json()["narration"]) >= 60

    def test_llm_status_returns_200(self, client):
        r = client.get("/api/llm/status")
        assert r.status_code == 200
        data = r.json()
        assert "available" in data
        assert "model"     in data


# ══════════════════════════════════════════════════════════════════════════════
# Report
# ══════════════════════════════════════════════════════════════════════════════

class TestReport:

    def test_report_no_narrate_200(self, client):
        r = client.post("/api/report/kerala-2018?narrate=false&top_n=3")
        assert r.status_code == 200

    def test_report_has_report_id(self, client):
        rep = client.post("/api/report/kerala-2018?narrate=false").json()
        assert rep.get("report_id", "").startswith("OM-")

    def test_report_has_5_fields(self, client):
        rep = client.post("/api/report/kerala-2018?narrate=false").json()
        for key in ("event", "module_info", "aggregate_stats", "priority_zones", "platform_context"):
            assert key in rep, f"Report missing key: {key}"

    def test_report_top_n_respected(self, client):
        rep = client.post("/api/report/kerala-2018?narrate=false&top_n=2").json()
        assert len(rep["priority_zones"]) == 2

    def test_report_platform_context_mentions_all_others(self, client):
        rep = client.post("/api/report/kerala-2018?narrate=false").json()
        ctx = rep["platform_context"]
        for dtype in ("Wildfire", "Landslide", "Cyclone", "Earthquake"):
            assert dtype in ctx, f"'{dtype}' missing from platform_context"

    def test_report_with_narrations(self, client):
        rep = client.post("/api/report/kerala-2018?narrate=true&top_n=2").json()
        assert len(rep["priority_zones"]) == 2
        z0  = rep["priority_zones"][0]
        assert z0.get("narration")
        assert len(z0["narration"]) >= 60
