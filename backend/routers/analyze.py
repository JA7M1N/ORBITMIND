"""
OrbitalMind — Analysis Router v2
===================================
POST /api/analyze

Always returns immediately with a task_id. A BackgroundTask simulates
(DEMO_MODE) or runs (live) the detection pipeline, updating a shared
task_progress dict that the WebSocket router streams to the client.

Request body: AnalyzeRequest
  {
    "event_id":      "kerala_2018",
    "disaster_type": "flood",
    "demo_mode":     true
  }

Response (immediate, all modes):
  {
    "task_id":       "<uuid>",
    "status":        "running",
    "progress":      0,
    "message":       "Starting flood analysis...",
    "disaster_type": "flood",
    "event_id":      "kerala_2018"
  }

The WebSocket at /api/ws/progress?task_id=X streams progress to 100%,
then attaches the full DetectionResult to the final message.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException

from backend.config import settings
from backend.schemas.api_schemas import AnalyzeRequest

router = APIRouter(prefix="/analyze", tags=["Analyze"])

# ── Shared in-process task store ──────────────────────────────────────────────
# {task_id: {status, progress, message, disaster_type, event_id, result, error}}
# Populated by background tasks; read by WS router and GET /api/tasks/{task_id}
task_progress: dict[str, dict[str, Any]] = {}

# Progress step definitions per disaster type
# Each entry: (progress_pct, message, delay_s)
_STEPS: dict[str, list[tuple[int, str, float]]] = {
    "flood": [
        (10,  "Connecting to Sentinel-1 SAR archive...",         0.3),
        (20,  "Loading SAR imagery (VV + VH polarisation)...",   0.4),
        (35,  "Pre-processing: speckle filtering + geocoding...",0.35),
        (50,  "Running Attention U-Net flood segmentation...",   0.6),
        (65,  "Applying confidence threshold (>0.55)...",        0.3),
        (75,  "Overlaying OSM infrastructure layer...",          0.4),
        (85,  "Spatial join: hospitals, schools, bridges...",    0.35),
        (90,  "Calculating district priority scores...",         0.3),
        (95,  "Generating GeoJSON output...",                    0.25),
        (100, "Analysis complete. 8 districts prioritised.",     0.0),
    ],
    "wildfire": [
        (10,  "Connecting to Sentinel-2 MSI archive...",           0.3),
        (20,  "Loading SWIR bands 11 + 12 (fire-sensitive)...",    0.4),
        (35,  "Calculating Normalised Burn Ratio (NBR)...",        0.4),
        (50,  "Computing dNBR (pre- vs post-fire difference)...", 0.5),
        (65,  "Classifying burn severity (low/medium/high)...",    0.35),
        (75,  "Mapping evacuation route disruptions...",           0.4),
        (85,  "Integrating MODIS active fire hotspots...",        0.3),
        (90,  "Scoring wildfire impact zones by population...",   0.3),
        (95,  "Generating burn perimeter GeoJSON...",             0.25),
        (100, "Analysis complete. Fire extent mapped.",           0.0),
    ],
    "landslide": [
        (10,  "Loading Sentinel-1 InSAR image pair...",           0.3),
        (20,  "Computing SAR coherence between acquisitions...", 0.5),
        (35,  "Detecting coherence loss (slide indicator)...",    0.4),
        (50,  "Loading SRTM 30 m digital elevation model...",    0.4),
        (65,  "Computing slope stability index (SSI)...",         0.4),
        (75,  "Delineating slide boundaries from DEM...",         0.35),
        (85,  "Overlaying road network disruptions...",           0.3),
        (90,  "Scoring slope-failure impact zones...",            0.3),
        (95,  "Exporting landslide mask GeoJSON...",              0.25),
        (100, "Analysis complete. Slide extents mapped.",         0.0),
    ],
    "cyclone": [
        (10,  "Loading INSAT-3D IR + WV channel data...",          0.3),
        (20,  "Applying Dvorak cloud-top temperature technique...",0.5),
        (35,  "Estimating max sustained wind radius...",           0.4),
        (50,  "Running coastal storm surge inundation model...",  0.5),
        (65,  "Delineating wind-speed zone polygons...",           0.35),
        (75,  "Overlaying coastal infrastructure layer...",        0.4),
        (85,  "Scoring districts by wind speed + surge...",        0.3),
        (90,  "Merging IMD best-track advisory data...",           0.3),
        (95,  "Generating impact zone GeoJSON...",                 0.25),
        (100, "Analysis complete. Cyclone impact zones ready.",   0.0),
    ],
    "earthquake": [
        (10,  "Loading Sentinel-1 SAR InSAR pair...",              0.3),
        (20,  "Computing differential interferogram (D-InSAR)...",0.55),
        (35,  "Unwrapping phase: mapping co-seismic deformation..",0.5),
        (50,  "Loading USGS ShakeMap PGA contours...",             0.35),
        (65,  "Identifying surface rupture zones...",              0.4),
        (75,  "Estimating building damage probability (PGA)...",  0.4),
        (85,  "Overlaying census block population data...",        0.3),
        (90,  "Calculating earthquake impact priority scores...", 0.3),
        (95,  "Generating damage assessment GeoJSON...",           0.25),
        (100, "Analysis complete. Damage zones prioritised.",      0.0),
    ],
}


# ── Background task ───────────────────────────────────────────────────────────

async def _run_demo_pipeline(task_id: str, event_id: str, disaster_type: str) -> None:
    """Simulate detection pipeline progress, then attach full result at 100%."""
    steps = _STEPS.get(disaster_type, _STEPS["flood"])

    for pct, msg, delay in steps:
        task_progress[task_id].update({
            "progress": pct,
            "message":  msg,
            "status":   "running" if pct < 100 else "complete",
        })
        if delay > 0:
            await asyncio.sleep(delay)

    # Load and attach the full DetectionResult at completion
    if task_progress[task_id]["status"] == "complete":
        try:
            from backend.services import demo_loader
            from backend.services.demo_loader import load_all_events

            events    = load_all_events()
            norm      = event_id.replace("-", "_")
            event_meta = next(
                (e for e in events if e["event_id"] == norm),
                {"event_id": norm, "display_name": norm, "region": "", "date_start": ""},
            )
            result = demo_loader.build_detection_result(norm, disaster_type, event_meta)
            task_progress[task_id]["result"] = result
        except Exception as exc:
            detail = f"Failed to load demo result: {exc}" if settings.DEMO_MODE else "Internal pipeline error."
            task_progress[task_id].update({
                "status": "error",
                "error":  detail,
            })


async def _run_live_pipeline(task_id: str, event_id: str, disaster_type: str) -> None:
    """Live inference — flood only in Phase 1; others return Phase 2 error."""
    if disaster_type != "flood":
        task_progress[task_id].update({
            "status":   "error",
            "progress": 0,
            "error":    (
                f"Module '{disaster_type}' is in Phase 2 development. "
                "Live inference not yet available. Use demo_mode=true."
            ),
        })
        return

    # Flood live path — delegates to MLService in a thread
    steps = _STEPS["flood"]
    try:
        from backend.services.ml_service import MLService
        _svc = MLService()
        for pct, msg, delay in steps[:-1]:   # all but final
            task_progress[task_id].update({"progress": pct, "message": msg})
            await asyncio.sleep(delay)
        # Run the actual inference (blocking — run in executor)
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: _svc.run_detection_demo(event_id, "flood"),
        )
        task_progress[task_id].update({
            "progress": 100,
            "status":   "complete",
            "message":  "Analysis complete.",
            "result":   result,
        })
    except Exception as exc:
        detail = str(exc) if settings.DEMO_MODE else "Internal pipeline error during detection inference."
        task_progress[task_id].update({
            "status": "error",
            "error":  detail,
        })


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.post(
    "",
    summary="Run disaster detection (demo or live)",
    response_description="Task handle — stream progress via WS /api/ws/progress?task_id=X",
    status_code=202,
)
async def analyze(
    request: AnalyzeRequest,
    background_tasks: BackgroundTasks,
) -> dict:
    """Start a detection analysis and return a task handle immediately.

    **Always returns 202 Accepted in < 5 ms** — the detection runs in the background.
    Subscribe to ``WS /api/ws/progress?task_id=<task_id>`` for real-time progress.
    Poll ``GET /api/tasks/{task_id}`` if WebSocket is unavailable.

    DEMO_MODE progress: 0 → 100 % over ~3 seconds with disaster-specific messages.
    Live mode (flood only): runs actual FloodModule inference (~4–8 s on RTX 3050).

    Parameters
    ----------
    request : AnalyzeRequest
        ``event_id``, ``disaster_type``, ``demo_mode``.

    Returns
    -------
    dict
        ``task_id``, ``status``, ``progress``, ``message``, ``disaster_type``.

    Raises
    ------
    422
        If ``disaster_type`` is not in SUPPORTED_DISASTERS.
    """
    dtype = request.disaster_type
    if dtype not in settings.SUPPORTED_DISASTERS:
        raise HTTPException(
            status_code=422,
            detail=f"disaster_type '{dtype}' not supported. "
                   f"Valid: {settings.SUPPORTED_DISASTERS}",
        )

    task_id = str(uuid.uuid4())
    norm_eid = request.event_id.replace("-", "_")

    # Initialise task record immediately
    task_progress[task_id] = {
        "task_id":      task_id,
        "status":       "running",
        "progress":     0,
        "message":      f"Starting {dtype} analysis...",
        "disaster_type": dtype,
        "event_id":     norm_eid,
        "result":       None,
        "error":        None,
        "created_at":   time.time(),
    }

    # Schedule background work
    use_demo = request.demo_mode if not settings.DEMO_MODE else True
    if use_demo:
        background_tasks.add_task(_run_demo_pipeline, task_id, norm_eid, dtype)
    else:
        background_tasks.add_task(_run_live_pipeline, task_id, norm_eid, dtype)

    return task_progress[task_id]
