"""
OrbitalMind — Copilot Router
==============================
Exposes the EO Conversational Copilot via two HTTP endpoints:

  POST /api/chat               — submit a question, get LLM reply + map action
  GET  /api/chat/suggestions   — fetch default prompt chips for the active module

Design notes
------------
- The router validates disaster_type against SUPPORTED_DISASTERS before
  calling the service, so the service layer never sees an invalid type.
- active_zone is optional: the copilot works with or without a selected zone;
  the system prompt tells the LLM "None selected" if it's absent.
- On Ollama failure the service returns a human-readable error in ``reply``
  rather than raising an HTTP 500 — the copilot should degrade gracefully
  (the map and priority list still work even if the LLM is down).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field, field_validator

from backend.config import settings
from backend.data.copilot_suggestions import SUGGESTIONS
from backend.services.copilot_service import CopilotService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Copilot"])

# ── Request model ──────────────────────────────────────────────────────────────


class ChatRequest(BaseModel):
    """Payload for a single copilot turn.

    Attributes
    ----------
    message:
        Plain-English question from the emergency manager (1–500 chars).
    event_id:
        Active event identifier shown on the map (e.g. ``"kerala-2018"``).
    disaster_type:
        Active disaster module (must be in SUPPORTED_DISASTERS).
    active_zone:
        Currently highlighted zone name in the map UI, or None if no zone
        is selected. Used so the copilot can give zone-specific answers.
    """

    message:       str       = Field(..., min_length=1, max_length=500)
    event_id:      str       = Field(..., min_length=1)
    disaster_type: str       = Field(..., min_length=1)
    active_zone:   str | None = Field(default=None)

    @field_validator("message")
    @classmethod
    def sanitize_message(cls, v: str) -> str:
        """Strip HTML tags, control characters, and leading/trailing whitespace."""
        # Remove non-printable control characters
        v = "".join(ch for ch in v if ch.isprintable() or ch in ("\n", "\r", "\t"))
        # Strip HTML tags to prevent HTML injections
        import re
        v = re.sub(r"<[^>]*>", "", v)
        v = v.strip()
        if not v:
            raise ValueError("message must contain printable characters and cannot be empty after sanitization")
        return v

    model_config = {"json_schema_extra": {
        "examples": [
            {
                "message":       "Show me Thrissur",
                "event_id":      "kerala-2018",
                "disaster_type": "flood",
                "active_zone":   "Idukki",
            }
        ]
    }}


# ── Response model ─────────────────────────────────────────────────────────────


class ChatResponse(BaseModel):
    """Copilot reply with optional map command.

    Attributes
    ----------
    reply:
        Clean LLM-generated answer (MAP_ACTION tags stripped).
    map_action:
        Structured map command or None. Possible shapes:
        ``{"action": "ZOOM", "target": "Thrissur"}``
        ``{"action": "HIGHLIGHT", "layer": "hospitals"}``
    event_id:
        Echoed back so the frontend can route to the correct module.
    disaster_type:
        Echoed back for the same reason.
    """

    reply:         str
    map_action:    dict | None
    event_id:      str
    disaster_type: str


class SuggestionsResponse(BaseModel):
    """Default prompt chips for a disaster module."""

    suggestions:   list[str]
    disaster_type: str


# ── Endpoints ──────────────────────────────────────────────────────────────────


@router.post(
    "/chat",
    response_model=ChatResponse,
    summary="Ask the EO Copilot a question",
    description=(
        "Submit a plain-English question about the active disaster event. "
        "Returns a 2-3 sentence operational answer grounded in the satellite "
        "analysis data, plus an optional map control command (ZOOM / HIGHLIGHT)."
    ),
)
async def post_chat(body: ChatRequest) -> ChatResponse:
    """Handle a single copilot turn.

    Validates the disaster_type, builds the context block, calls Ollama,
    strips MAP_ACTION tags, and returns a structured response.

    Raises
    ------
    422 Unprocessable Entity:
        If ``message`` is empty/too long, ``event_id`` is empty, or
        ``disaster_type`` is not in SUPPORTED_DISASTERS.
    """
    # Validate disaster_type — return 422 (not 400) to match FastAPI convention
    if body.disaster_type not in settings.SUPPORTED_DISASTERS:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=422,
            detail=(
                f"disaster_type '{body.disaster_type}' is not supported. "
                f"Valid types: {settings.SUPPORTED_DISASTERS}"
            ),
        )

    service = CopilotService()
    result  = await service.query_copilot(
        message=body.message,
        event_id=body.event_id,
        disaster_type=body.disaster_type,
        active_zone=body.active_zone,
    )

    return ChatResponse(**result)


@router.get(
    "/chat/suggestions",
    response_model=SuggestionsResponse,
    summary="Fetch default prompt suggestions",
    description=(
        "Returns 3 operational prompt chips for the given disaster module. "
        "If the disaster_type is unrecognised, falls back to flood suggestions."
    ),
)
async def get_suggestions(
    disaster_type: str = Query(
        default="flood",
        description="Disaster module type (flood | wildfire | landslide | cyclone | earthquake)",
    ),
) -> SuggestionsResponse:
    """Return the suggestion chips for a disaster module.

    Always returns exactly 3 suggestions. Unknown types get the flood
    fallback so the UI never shows an empty chip row.
    """
    chips = SUGGESTIONS.get(disaster_type, SUGGESTIONS["flood"])
    return SuggestionsResponse(
        suggestions=chips,
        disaster_type=disaster_type,
    )
