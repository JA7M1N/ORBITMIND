"""
OrbitalMind — Modules Router
==============================
GET /api/modules          -> list all 5 disaster module metadata records
GET /api/modules/{type}   -> single module metadata by disaster_type

The response is hardcoded here (no ML service dependency) so the endpoint
works immediately on a cold server without PyTorch / model weights loaded.
The ml_service.get_available_modules() approach is reserved for Phase 2
when live inference metadata is needed.

Module status values
---------------------
  "live"  -> full inference pipeline operational (FloodModule, Phase 1)
  "demo"  -> pre-computed results only, live inference in development
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/modules", tags=["Modules"])


# ── Module registry (hardcoded for fast startup + zero ML dependency) ─────────

_MODULES: list[dict] = [
    {
        "disaster_type":    "flood",
        "display_name":     "Flood Detection",
        "icon":             "droplets",
        "color":            "#1e40af",
        "status":           "live",
        "satellite_sources": ["Sentinel-1 SAR (C-band, VV+VH)", "Copernicus Emergency Management"],
        "detection_method": "Attention U-Net (ResNet-34 encoder, 4-channel SAR input)",
        "description":      (
            "Detects surface water inundation from Sentinel-1 SAR backscatter "
            "change using a trained Attention U-Net model. Outputs flood masks "
            "at 10 m resolution with per-pixel confidence scores."
        ),
        "priority_weights": {
            "population": 0.40,
            "infra":      0.30,
            "access":     0.20,
            "intensity":  0.10,
        },
        "phase": 1,
    },
    {
        "disaster_type":    "wildfire",
        "display_name":     "Wildfire Detection",
        "icon":             "flame",
        "color":            "#dc2626",
        "status":           "demo",
        "satellite_sources": ["Sentinel-2 MSI (SWIR bands 11+12)", "MODIS Active Fire"],
        "detection_method": "Normalised Burn Ratio (dNBR) + Random Forest classifier",
        "description":      (
            "Maps active burn perimeters and post-fire severity using Sentinel-2 "
            "SWIR imagery and differenced NBR. Integrates MODIS active fire hotspots "
            "for near-real-time burn front tracking."
        ),
        "priority_weights": {
            "population": 0.35,
            "infra":      0.25,
            "access":     0.25,
            "intensity":  0.15,
        },
        "phase": 2,
    },
    {
        "disaster_type":    "landslide",
        "display_name":     "Landslide Detection",
        "icon":             "mountain",
        "color":            "#92400e",
        "status":           "demo",
        "satellite_sources": ["Sentinel-1 SAR (InSAR coherence)", "SRTM 30 m DEM"],
        "detection_method": "SAR coherence change detection + slope stability index",
        "description":      (
            "Identifies slope failures by measuring SAR coherence loss between "
            "pre- and post-event images, combined with slope angle and lithology "
            "from the SRTM DEM to map susceptibility and extent."
        ),
        "priority_weights": {
            "population": 0.30,
            "infra":      0.25,
            "access":     0.30,
            "intensity":  0.15,
        },
        "phase": 2,
    },
    {
        "disaster_type":    "cyclone",
        "display_name":     "Cyclone Impact Assessment",
        "icon":             "wind",
        "color":            "#7c3aed",
        "status":           "demo",
        "satellite_sources": ["INSAT-3D (IR + WV)", "IMD Best-Track Archive"],
        "detection_method": "Wind-radius model (Dvorak technique) + storm surge overlay",
        "description":      (
            "Delineates cyclone impact zones from INSAT-3D cloud-top temperature "
            "gradients using the Dvorak intensity estimation technique. Combines "
            "with storm surge inundation modelling for coastal impact assessment."
        ),
        "priority_weights": {
            "population": 0.30,
            "infra":      0.20,
            "access":     0.30,
            "intensity":  0.20,
        },
        "phase": 2,
    },
    {
        "disaster_type":    "earthquake",
        "display_name":     "Earthquake Damage Assessment",
        "icon":             "activity",
        "color":            "#c2410c",
        "status":           "demo",
        "satellite_sources": ["Sentinel-1 SAR (InSAR displacement)", "USGS ShakeMap"],
        "detection_method": "Differential InSAR (D-InSAR) co-seismic deformation + ShakeMap PGA",
        "description":      (
            "Maps co-seismic ground deformation using Sentinel-1 InSAR phase "
            "difference to identify surface ruptures and subsidence areas. "
            "Integrates USGS ShakeMap PGA contours for building damage "
            "probability estimation."
        ),
        "priority_weights": {
            "population": 0.35,
            "infra":      0.30,
            "access":     0.20,
            "intensity":  0.15,
        },
        "phase": 2,
    },
]

# Quick lookup dict
_MODULE_MAP: dict[str, dict] = {m["disaster_type"]: m for m in _MODULES}


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get(
    "",
    summary="List all disaster modules",
    response_description="Metadata for all 5 registered disaster modules",
)
async def list_modules() -> list[dict]:
    """Return metadata for every registered disaster module.

    Each record includes ``disaster_type``, ``display_name``, ``icon``,
    ``color``, ``status`` (live/demo), ``satellite_sources``,
    ``detection_method``, ``priority_weights``, and ``description``.

    Used by the frontend ``DisasterNav`` component to render module tabs.
    """
    return _MODULES


@router.get(
    "/{disaster_type}",
    summary="Get single module metadata",
    response_description="Metadata for one disaster module",
)
async def get_module(disaster_type: str) -> dict:
    """Return metadata for a single module identified by ``disaster_type``.

    Parameters
    ----------
    disaster_type : str
        One of: ``flood``, ``wildfire``, ``landslide``, ``cyclone``,
        ``earthquake``.

    Raises
    ------
    404
        If ``disaster_type`` is not registered.
    """
    module = _MODULE_MAP.get(disaster_type.lower().strip())
    if not module:
        raise HTTPException(
            status_code = 404,
            detail      = {
                "error":      f"Module '{disaster_type}' not found",
                "registered": list(_MODULE_MAP.keys()),
            },
        )
    return module
