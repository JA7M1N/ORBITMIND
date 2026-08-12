"""
OrbitalMind — ML Service Pydantic Schemas (v2)
===============================================
All request / response models for the ML service layer and the
``/api/modules``, ``/api/analyze``, and ``/api/events/{id}/zones`` endpoints.

Pydantic v2 conventions used throughout:
- ``model_config = ConfigDict(...)`` instead of inner ``class Config``
- ``Field(...)`` with ``description=`` for OpenAPI docs
- ``field_validator`` for cross-field constraints
- ``model_validator`` for compound invariants
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Module metadata
# ---------------------------------------------------------------------------

class PriorityWeights(BaseModel):
    """Weighting factors for the priority-scoring formula.

    Score = w_population × (pop/max_pop)
          + w_infra      × infra_score
          + w_access     × (1 − road_intact_ratio)
          + w_intensity  × intensity

    All four weights must sum to 1.0 (±0.01 tolerance).
    """

    model_config = ConfigDict(frozen=True)

    population: float = Field(..., ge=0.0, le=1.0, description="Population density weight")
    infra:      float = Field(..., ge=0.0, le=1.0, description="Infrastructure exposure weight")
    access:     float = Field(..., ge=0.0, le=1.0, description="Road inaccessibility weight")
    intensity:  float = Field(..., ge=0.0, le=1.0, description="Disaster intensity weight")

    @model_validator(mode="after")
    def weights_sum_to_one(self) -> "PriorityWeights":
        """Ensure the four weights sum to 1.0 within ±0.01 tolerance."""
        total = self.population + self.infra + self.access + self.intensity
        if abs(total - 1.0) > 0.01:
            raise ValueError(
                f"priority_weights must sum to 1.0, got {total:.4f}"
            )
        return self


class DisasterModuleInfo(BaseModel):
    """Full metadata record for a single disaster detection module.

    Returned by ``GET /api/modules`` and embedded in ``DetectionResult``.
    """

    model_config = ConfigDict(frozen=True)

    disaster_type:       str             = Field(..., description="Routing key, e.g. 'flood'")
    display_name:        str             = Field(..., description="Human-readable name")
    icon:                str             = Field(..., description="Emoji icon")
    color:               str             = Field(..., description="Hex colour for UI accents")
    status:              str             = Field(..., description="'live' or 'demo'")
    is_live:             bool            = Field(..., description="True if real ML inference is available")
    demo_event_id:       str             = Field(..., description="Canonical demo event slug")
    satellite_sources:   list[str]       = Field(..., description="GEE asset IDs")
    detection_method:    str             = Field(..., description="Short algorithm description")
    affected_infra_types: list[str]      = Field(..., description="Infrastructure categories queried")
    priority_weights:    PriorityWeights = Field(..., description="Scoring formula weights")
    description:         str             = Field(..., description="One-sentence module summary")

    @field_validator("status")
    @classmethod
    def status_must_be_valid(cls, v: str) -> str:
        if v not in ("live", "demo"):
            raise ValueError(f"status must be 'live' or 'demo', got '{v}'")
        return v

    @field_validator("color")
    @classmethod
    def color_must_be_hex(cls, v: str) -> str:
        if not v.startswith("#") or len(v) not in (4, 7):
            raise ValueError(f"color must be a hex string like '#1e40af', got '{v}'")
        return v


# ---------------------------------------------------------------------------
# Detection results
# ---------------------------------------------------------------------------

class ZoneStats(BaseModel):
    """Disaster-type-specific scene statistics extracted from detection output.

    The exact keys present depend on ``disaster_type``:

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

    All modules include ``feature_count`` and ``avg_confidence``.
    """

    model_config = ConfigDict(extra="allow")   # allow disaster-specific keys

    feature_count:  int   = Field(..., ge=0, description="Number of GeoJSON features")
    avg_confidence: float = Field(..., ge=0.0, le=1.0, description="Mean detection confidence")

    # Optional disaster-specific fields (present when relevant)
    total_flooded_area_km2:  Optional[float] = None
    total_burned_area_km2:   Optional[float] = None
    total_slide_area_km2:    Optional[float] = None
    total_damage_area_km2:   Optional[float] = None
    high_severity_pct:       Optional[float] = None   # wildfire
    avg_slope_angle:         Optional[float] = None   # landslide
    max_wind_speed_kmh:      Optional[float] = None   # cyclone
    storm_surge_max_m:       Optional[float] = None   # cyclone
    destroyed_pct:           Optional[float] = None   # earthquake


class DetectionResult(BaseModel):
    """Complete detection result returned by ``run_detection_demo()`` or
    after a live inference task completes.

    Returned by ``POST /api/analyze`` and ``GET /api/events/{id}/zones``.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    event_id:             str               = Field(..., description="Event slug or UUID")
    disaster_type:        str               = Field(..., description="Module routing key")
    source:               str               = Field(
        default="demo",
        description="'demo' (from disk) or 'unet_inference' (live ML)",
    )
    affected_zones_geojson: dict[str, Any]  = Field(
        ..., description="GeoJSON FeatureCollection of affected zones"
    )
    stats:                ZoneStats         = Field(..., description="Aggregate scene statistics")
    module_info:          DisasterModuleInfo = Field(..., description="Module metadata")

    @field_validator("affected_zones_geojson")
    @classmethod
    def geojson_must_be_feature_collection(cls, v: dict) -> dict:
        if v.get("type") != "FeatureCollection":
            raise ValueError(
                f"affected_zones_geojson must be a GeoJSON FeatureCollection, "
                f"got type='{v.get('type')}'"
            )
        if "features" not in v:
            raise ValueError("affected_zones_geojson must contain a 'features' list")
        return v


# ---------------------------------------------------------------------------
# Background inference task status
# ---------------------------------------------------------------------------

class InferenceStatus(BaseModel):
    """Status record for a background ML inference task.

    Created when ``run_detection_live()`` is called and updated as the
    Sentinel-1 download + U-Net inference pipeline progresses.

    Polled via ``GET /api/tasks/{task_id}`` or pushed via WebSocket
    ``WS /api/ws/progress``.
    """

    model_config = ConfigDict(frozen=False)   # mutable — updated in-place

    task_id:  str   = Field(..., description="UUID4 task identifier")
    status:   str   = Field(
        ...,
        description="One of: 'pending' | 'running' | 'complete' | 'error'",
    )
    progress: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Completion percentage (0–100)",
    )
    message:  str   = Field(default="", description="Human-readable status message")
    result:   Optional[dict[str, Any]] = Field(
        default=None,
        description="Detection result dict when status='complete'",
    )
    error:    Optional[dict[str, Any]] = Field(
        default=None,
        description="Error detail dict when status='error'",
    )

    @field_validator("status")
    @classmethod
    def status_must_be_valid(cls, v: str) -> str:
        allowed = ("pending", "running", "complete", "error")
        if v not in allowed:
            raise ValueError(f"status must be one of {allowed}, got '{v}'")
        return v


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class AnalyzeRequest(BaseModel):
    """Request body for ``POST /api/analyze``."""

    event_id:     str       = Field(..., description="Event slug or UUID")
    disaster_type: str      = Field(..., description="Module routing key")
    demo_mode:    bool      = Field(
        default=True,
        description="If True, read from demo_data on disk; if False, run live ML",
    )
    bbox:         Optional[list[float]] = Field(
        default=None,
        description="[min_lon, min_lat, max_lon, max_lat] for live mode",
    )
    date_range:   Optional[list[str]] = Field(
        default=None,
        description="[start_date, end_date] ISO-8601 for live mode",
    )

    @field_validator("bbox")
    @classmethod
    def bbox_must_have_four_elements(cls, v: Optional[list[float]]) -> Optional[list[float]]:
        if v is not None and len(v) != 4:
            raise ValueError("bbox must have exactly 4 elements: [min_lon, min_lat, max_lon, max_lat]")
        return v

    @model_validator(mode="after")
    def live_mode_requires_bbox_and_dates(self) -> "AnalyzeRequest":
        if not self.demo_mode:
            if self.bbox is None:
                raise ValueError("bbox is required when demo_mode=False")
            if self.date_range is None or len(self.date_range) != 2:
                raise ValueError("date_range [start, end] is required when demo_mode=False")
        return self
