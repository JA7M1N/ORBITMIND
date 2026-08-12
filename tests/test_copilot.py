"""
tests/test_copilot.py
======================
Integration tests for the EO Copilot endpoints.

Run with:
    pytest tests/test_copilot.py -v

These tests use httpx.AsyncClient with the FastAPI app in ASGI mode so
they never touch the real Ollama server or database. Ollama is patched via
unittest.mock, ensuring tests are fast and deterministic.

DEMO_MODE is set to True in the test environment so all context is served
from hardcoded fixtures.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# ── Path setup: ensure repo root is importable ────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Force DEMO_MODE=True and clear settings cache before the app is imported
os.environ.setdefault("DEMO_MODE", "true")

# ── Pre-import the copilot service so the patch path resolves ─────────────────
# patch("backend.services.copilot_service.ollama", ...) requires the module to
# already be in sys.modules at the time patch() resolves the dotted path.
import backend.services.copilot_service as _copilot_svc_mod  # noqa: E402

# ── Mock Ollama before any import that triggers the service ────────────────────
_MOCK_OLLAMA_RESPONSE = {
    "message": {
        "content": (
            "Idukki is the highest priority zone with a score of 0.94 and "
            "only 38% of roads passable. Prioritise helicopter-based rescue "
            "operations there immediately.\n"
            "MAP_ACTION::ZOOM::Thrissur"
        )
    }
}


def _make_ollama_mock() -> MagicMock:
    mock = MagicMock()
    mock.chat.return_value = _MOCK_OLLAMA_RESPONSE
    return mock


# Patch ollama at the module level so CopilotService picks it up
@pytest.fixture(autouse=True)
def patch_ollama():
    """Replace ollama.chat with a synchronous mock for all copilot tests."""
    with patch.object(_copilot_svc_mod, "ollama", _make_ollama_mock()):
        yield


# ── App fixture ────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def client():
    """Async HTTPX client wired to the FastAPI app without a real HTTP server."""
    # Clear settings cache so env vars applied above take effect
    from backend.config import get_settings
    get_settings.cache_clear()

    from backend.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


# ── Test: POST /api/chat — happy path ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_chat_valid_flood_message(client: AsyncClient):
    """Valid flood chat request returns reply string and a map_action dict."""
    resp = await client.post(
        "/api/chat",
        json={
            "message":       "Which district needs rescue boats first?",
            "event_id":      "kerala-2018",
            "disaster_type": "flood",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data["reply"], str), "reply must be a string"
    assert len(data["reply"]) > 0,         "reply must not be empty"
    # map_action is present (may be None or a dict — both are valid)
    assert "map_action" in data
    assert data["event_id"]      == "kerala-2018"
    assert data["disaster_type"] == "flood"


# ── Test: POST /api/chat — empty message returns 422 ──────────────────────────

@pytest.mark.asyncio
async def test_chat_empty_message_returns_422(client: AsyncClient):
    """Empty message must fail Pydantic validation with 422."""
    resp = await client.post(
        "/api/chat",
        json={
            "message":       "",          # violates min_length=1
            "event_id":      "kerala-2018",
            "disaster_type": "flood",
        },
    )
    assert resp.status_code == 422


# ── Test: POST /api/chat — invalid disaster_type returns 422 ──────────────────

@pytest.mark.asyncio
async def test_chat_invalid_disaster_type_returns_422(client: AsyncClient):
    """Unknown disaster_type must be rejected with 422."""
    resp = await client.post(
        "/api/chat",
        json={
            "message":       "What happened?",
            "event_id":      "kerala-2018",
            "disaster_type": "tsunami",   # not in SUPPORTED_DISASTERS
        },
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert "tsunami" in detail.lower() or "not supported" in detail.lower()


# ── Test: MAP_ACTION::ZOOM extracted for "Show me Thrissur" ───────────────────

@pytest.mark.asyncio
async def test_chat_show_zone_produces_zoom_action(client: AsyncClient):
    """'Show me Thrissur' → map_action with action=ZOOM and target=Thrissur."""
    resp = await client.post(
        "/api/chat",
        json={
            "message":       "Show me Thrissur",
            "event_id":      "kerala-2018",
            "disaster_type": "flood",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    # Our mock always includes MAP_ACTION::ZOOM::Thrissur in the reply
    assert data["map_action"] is not None, "Expected a map_action but got None"
    assert data["map_action"]["action"] == "ZOOM"
    assert data["map_action"]["target"] == "Thrissur"
    # The MAP_ACTION tag must NOT appear in the clean reply text
    assert "MAP_ACTION" not in data["reply"]


# ── Test: parse_map_commands unit tests ───────────────────────────────────────

@pytest.mark.asyncio
async def test_parse_map_commands_zoom():
    """parse_map_commands strips tag and returns ZOOM action."""
    from backend.services.copilot_service import CopilotService
    svc = CopilotService()
    text = "Idukki is the priority zone.\nMAP_ACTION::ZOOM::Idukki"
    clean, action = await svc.parse_map_commands(text)
    assert "MAP_ACTION" not in clean
    assert action == {"action": "ZOOM", "target": "Idukki"}


@pytest.mark.asyncio
async def test_parse_map_commands_highlight():
    """parse_map_commands strips tag and returns HIGHLIGHT action."""
    from backend.services.copilot_service import CopilotService
    svc = CopilotService()
    text = "Six hospitals are in the flood zone.\nMAP_ACTION::HIGHLIGHT::hospitals"
    clean, action = await svc.parse_map_commands(text)
    assert "MAP_ACTION" not in clean
    assert action == {"action": "HIGHLIGHT", "layer": "hospitals"}


@pytest.mark.asyncio
async def test_parse_map_commands_no_action():
    """parse_map_commands returns None action when no tag present."""
    from backend.services.copilot_service import CopilotService
    svc = CopilotService()
    text = "Idukki has the highest priority score."
    clean, action = await svc.parse_map_commands(text)
    assert clean == text
    assert action is None


# ── Test: GET /api/chat/suggestions — wildfire ────────────────────────────────

@pytest.mark.asyncio
async def test_suggestions_wildfire(client: AsyncClient):
    """Wildfire suggestions endpoint returns exactly 3 wildfire-themed chips."""
    resp = await client.get("/api/chat/suggestions?disaster_type=wildfire")
    assert resp.status_code == 200
    data = resp.json()
    assert data["disaster_type"] == "wildfire"
    assert isinstance(data["suggestions"], list)
    assert len(data["suggestions"]) == 3
    # At least one suggestion should mention wildfire-specific framing
    all_text = " ".join(data["suggestions"]).lower()
    assert any(
        kw in all_text
        for kw in ("fire", "evacuat", "village", "hospital", "perimeter")
    )


# ── Test: GET /api/chat/suggestions — unknown type falls back to flood ─────────

@pytest.mark.asyncio
async def test_suggestions_unknown_type_returns_flood_fallback(client: AsyncClient):
    """Unknown disaster_type returns 3 flood suggestions as the default."""
    resp = await client.get("/api/chat/suggestions?disaster_type=tsunami")
    assert resp.status_code == 200
    data = resp.json()
    # tsunami is not a valid type — should still return 3 items (flood fallback)
    assert isinstance(data["suggestions"], list)
    assert len(data["suggestions"]) == 3


# ── Test: active_zone=None is accepted ────────────────────────────────────────

@pytest.mark.asyncio
async def test_chat_no_active_zone(client: AsyncClient):
    """Omitting active_zone (null) is valid — copilot works without zone context."""
    resp = await client.post(
        "/api/chat",
        json={
            "message":       "What is the total population affected?",
            "event_id":      "kerala-2018",
            "disaster_type": "flood",
            "active_zone":   None,
        },
    )
    assert resp.status_code == 200
    assert isinstance(resp.json()["reply"], str)


# ── Test: message too long returns 422 ────────────────────────────────────────

@pytest.mark.asyncio
async def test_chat_message_too_long_returns_422(client: AsyncClient):
    """Message exceeding 500 characters must fail validation with 422."""
    resp = await client.post(
        "/api/chat",
        json={
            "message":       "A" * 501,   # violates max_length=500
            "event_id":      "kerala-2018",
            "disaster_type": "flood",
        },
    )
    assert resp.status_code == 422


# ── Test: all 5 suggestion sets have 3 items ──────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("dtype", ["flood", "wildfire", "landslide", "cyclone", "earthquake"])
async def test_all_suggestion_types_return_3_items(client: AsyncClient, dtype: str):
    """Every disaster type has exactly 3 suggestion chips."""
    resp = await client.get(f"/api/chat/suggestions?disaster_type={dtype}")
    assert resp.status_code == 200
    assert len(resp.json()["suggestions"]) == 3
