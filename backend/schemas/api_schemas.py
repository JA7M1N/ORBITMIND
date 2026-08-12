"""
OrbitalMind — API Schemas (Pydantic v2)
=========================================
Request and response models for all OrbitalMind endpoints.

All models use Pydantic v2 syntax (model_config, Field with json_schema_extra).
Import these in routers for type-safe request parsing and OpenAPI doc generation.
"""
from __future__ import annotations

from typing import Any, Literal, Optional
from pydantic import BaseModel, Field, field_validator


# ── Request schemas ───────────────────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    """POST /api/analyze request body."""

    event_id: str = Field(
        ...,
        description="Event slug (e.g. 'kerala_2018') or UUID.",
        examples=["kerala_2018"],
    )
    disaster_type: str = Field(
        ...,
        description="One of: flood | wildfire | landslide | cyclone | earthquake",
        examples=["flood"],
    )
    demo_mode: bool = Field(
        default=True,
        description=(
            "True = read from pre-computed disk data (<200 ms, no GPU). "
            "False = start live inference background task (flood only in Phase 1)."
        ),
    )
    bbox: Optional[list[float]] = Field(
        default=None,
        description="[west, south, east, north] bounding box. Required when demo_mode=False.",
        examples=[[76.0, 9.5, 77.5, 11.0]],
    )
    date_range: Optional[list[str]] = Field(
        default=None,
        description="['YYYY-MM-DD', 'YYYY-MM-DD'] start/end. Required when demo_mode=False.",
        examples=[["2018-08-01", "2018-08-20"]],
    )

    @field_validator("disaster_type")
    @classmethod
    def validate_disaster_type(cls, v: str) -> str:
        valid = {"flood", "wildfire", "landslide", "cyclone", "earthquake"}
        v = v.lower().strip()
        if v not in valid:
            raise ValueError(f"disaster_type must be one of {sorted(valid)}, got '{v}'")
        return v

    @field_validator("bbox")
    @classmethod
    def validate_bbox(cls, v: Optional[list[float]]) -> Optional[list[float]]:
        if v is not None and len(v) != 4:
            raise ValueError("bbox must have exactly 4 values: [west, south, east, north]")
        return v

    @field_validator("date_range")
    @classmethod
    def validate_date_range(cls, v: Optional[list[str]]) -> Optional[list[str]]:
        if v is not None and len(v) != 2:
            raise ValueError("date_range must have exactly 2 values: ['start', 'end']")
        return v


# ── Response schemas ──────────────────────────────────────────────────────────

class TaskStatus(BaseModel):
    """Returned immediately from POST /api/analyze (live mode) and polled via WS."""

    task_id:       str   = Field(..., description="UUID for tracking this inference job.")
    status:        str   = Field(..., description="pending | running | complete | error")
    progress:      float = Field(default=0.0, ge=0.0, le=100.0, description="0–100 %")
    message:       str   = Field(default="", description="Human-readable stage description.")
    disaster_type: str   = Field(default="", description="Module that processed this task.")
    event_id:      str   = Field(default="", description="Event slug being analysed.")
    result:        Optional[dict[str, Any]] = Field(
        default=None, description="Full DetectionResult — only set when status=complete."
    )
    error:         Optional[str] = Field(
        default=None, description="Error message — only set when status=error."
    )


class ProgressMessage(BaseModel):
    """WebSocket message pushed every 500 ms during inference."""

    task_id:  str   = Field(..., description="Task UUID.")
    progress: float = Field(..., ge=0.0, le=100.0)
    status:   str   = Field(..., description="running | complete | error")
    message:  str   = Field(default="")
    disaster_type: str = Field(default="")


class PriorityZone(BaseModel):
    """A single ranked district from the priority scoring engine."""

    rank:                int
    zone:                str
    score:               float = Field(ge=0.0, le=1.0)
    hospitals:           int   = Field(ge=0)
    schools:             int   = Field(ge=0)
    bridges:             int   = Field(ge=0)
    pop:                 int   = Field(ge=0, description="Population (Census 2011)")


class ModuleInfo(BaseModel):
    """Metadata about the ML module that processed an event."""

    module:           str
    model:            str
    satellite:        str
    resolution_m:     int
    inference_time_s: float
    phase:            int
    is_live:          bool


class DetectionResult(BaseModel):
    """Full result returned by /api/events/{event_id}/zones and POST /api/analyze (demo)."""

    event_id:      str
    disaster_type: str
    display_name:  str
    region:        str
    date:          str
    status:        str = Field(description="demo | live | archived")
    module_info:   dict[str, Any]
    affected_zones_geojson: dict[str, Any] = Field(
        description="GeoJSON FeatureCollection with priority metadata on each feature."
    )
    priority_zones: list[dict[str, Any]]
    stats:          dict[str, Any]


class HealthResponse(BaseModel):
    """GET /health response."""

    status:              Literal["ok"]
    version:             str
    demo_mode:           bool
    supported_disasters: list[str]
    ollama_model:        str
    service:             str


class EventMeta(BaseModel):
    """One event record from events_manifest.json."""

    event_id:        str
    disaster_type:   str
    display_name:    str
    region:          str
    state:           Optional[str] = None
    date_start:      Optional[str] = None
    date_end:        Optional[str] = None
    status:          str = "demo"
    data_source:     Optional[str] = None
    thumbnail_color: Optional[str] = None
    description:     Optional[str] = None
