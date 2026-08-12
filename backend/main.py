"""
OrbitalMind — FastAPI Application v2.0.0
==========================================
Entry point for the OrbitalMind backend API.

Start server
------------
From OrbitalMind/ repo root:

    uvicorn backend.main:app --reload --port 8000

Or from inside backend/:

    uvicorn main:app --reload --port 8000

Interactive docs (after start)
-------------------------------
  Swagger UI : http://localhost:8000/docs
  ReDoc       : http://localhost:8000/redoc
  OpenAPI JSON: http://localhost:8000/openapi.json

API surface
-----------
  GET  /health                         -> service liveness check
  GET  /api/modules                    -> all 5 module metadata records
  GET  /api/modules/{disaster_type}    -> single module metadata
  POST /api/analyze                    -> demo or live detection
  GET  /api/events                     -> all 5 demo events from manifest
  GET  /api/events/{event_id}          -> single event metadata
  GET  /api/events/{event_id}/zones    -> DetectionResult (demo mode)
  GET  /api/events/{event_id}/stats    -> disaster-specific stats dict
  GET  /api/tasks/{task_id}            -> single task status (poll)
  WS   /api/ws/progress/{task_id}      -> real-time progress push

VRAM note (RTX 3050 — 4 GB)
----------------------------
  U-Net inference and Ollama CANNOT run at the same time.
  Wait for task status='complete' before calling /api/narrate.
  FloodModule calls torch.cuda.empty_cache() at end of run_detection().
"""
from __future__ import annotations

import json
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# ── Ensure repo root is on path ──────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# ── Settings ─────────────────────────────────────────────────────────────────
from backend.config import settings
from backend.middleware.rate_limit import RateLimitMiddleware

# ── Routers ──────────────────────────────────────────────────────────────────
from backend.routers import analyze, events, modules, narration, platform, tasks, ws
from backend.routers.copilot import router as copilot_router


# ── Lifespan ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — startup banner + module registry warm-up."""
    # ── Startup ───────────────────────────────────────────────────────────
    bar = "=" * 58
    print(f"\n{bar}")
    print(f"  OrbitalMind API v{settings.API_VERSION}  --  starting up")
    print(bar)
    print(f"  DEMO_MODE        : {settings.DEMO_MODE}")
    print(f"  DATABASE_URL     : {settings.DATABASE_URL[:40]}...")
    print(f"  OLLAMA_URL       : {settings.OLLAMA_URL}")
    print(f"  OLLAMA_MODEL     : {settings.OLLAMA_MODEL}")

    # Module registry warm-up (best-effort — never crashes startup)
    try:
        from ml.module_registry import list_modules as _list
        mods = _list()
        print(f"  Module registry  : {len(mods)} modules loaded")
        for m in mods:
            live = "LIVE" if m.get("is_live") else "demo"
            print(f"    [{live:4}]  {m['disaster_type']:<12}  {m['display_name']}")
    except Exception as exc:
        print(f"  [WARN] Module registry unavailable: {exc}")
        print(f"  Modules          : 5 (hardcoded fallback active)")

    # Demo manifest check
    manifest = _REPO_ROOT / "backend" / "demo_data" / "events_manifest.json"
    if manifest.exists():
        n = len(json.loads(manifest.read_text())["events"])
        print(f"  Demo events      : {n} events ready")
    else:
        print("  [WARN] events_manifest.json not found")

    print(bar)
    print(f"  Swagger UI       : http://localhost:8000/docs")
    print(f"  Modules endpoint : http://localhost:8000/api/modules")
    print(f"  Health endpoint  : http://localhost:8000/health")
    print(bar + "\n")

    print(f"OrbitalMind API started. DEMO_MODE={settings.DEMO_MODE}. Modules: 5")

    yield  # ── App runs ─────────────────────────────────────────────────

    # ── Shutdown ──────────────────────────────────────────────────────────
    print("\n  OrbitalMind API -- shutting down cleanly\n")


# ── App instance ──────────────────────────────────────────────────────────────

app = FastAPI(
    title       = settings.API_TITLE,
    description = (
        "AI-powered multi-disaster satellite intelligence platform.\n\n"
        "Transforms Sentinel-1 SAR and INSAT-3D imagery into prioritised "
        "disaster response zones for emergency authorities.\n\n"
        "**Phase 1 (Live):** Flood detection via Attention U-Net + PostGIS "
        "infrastructure overlay.\n\n"
        "**Phase 2 (Roadmap):** Wildfire, Landslide, Cyclone, Earthquake modules."
    ),
    version     = settings.API_VERSION,
    docs_url    = "/docs",
    redoc_url   = "/redoc",
    lifespan    = lifespan,
)


# ── CORS ──────────────────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins     = settings.CORS_ORIGINS,
    allow_credentials = True,
    allow_methods     = ["*"],
    allow_headers     = ["*"],
)

app.add_middleware(RateLimitMiddleware)


# ── Request timing middleware ─────────────────────────────────────────────────

@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    """Attach X-Process-Time (ms) to every response for latency monitoring."""
    t0       = time.perf_counter()
    response = await call_next(request)
    elapsed  = time.perf_counter() - t0
    response.headers["X-Process-Time"] = f"{elapsed * 1000:.1f}ms"
    return response


# ── Global exception handler ──────────────────────────────────────────────────

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Return structured JSON for any unhandled 500 error."""
    detail = str(exc) if settings.DEMO_MODE else "An unexpected error occurred."
    return JSONResponse(
        status_code = 500,
        content     = {
            "error":   "Internal server error",
            "detail":  detail,
            "path":    str(request.url),
        },
    )


# ── Health endpoint ───────────────────────────────────────────────────────────

@app.get(
    "/health",
    tags     = ["Health"],
    summary  = "Service liveness check",
)
async def health() -> dict:
    """Lightweight liveness probe used by health-check scripts and load balancers.

    Returns
    -------
    dict
        ``status``, ``demo_mode``, ``version``, ``supported_disasters``,
        ``ollama_model``.
    """
    return {
        "status":              "ok",
        "version":             settings.API_VERSION,
        "demo_mode":           settings.DEMO_MODE,
        "supported_disasters": settings.SUPPORTED_DISASTERS,
        "ollama_model":        settings.OLLAMA_MODEL,
        "service":             "OrbitalMind Platform API",
    }


# ── Routers ───────────────────────────────────────────────────────────────────

app.include_router(modules.router,    prefix="/api")
app.include_router(analyze.router,    prefix="/api")
app.include_router(events.router,     prefix="/api")
app.include_router(narration.router,  prefix="/api")
app.include_router(platform.router,   prefix="/api")
app.include_router(tasks.router,      prefix="/api")
app.include_router(ws.router,         prefix="/api")
app.include_router(copilot_router,    prefix="/api")  # EO Copilot — POST /api/chat


# ── Dev runner ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "backend.main:app",
        host      = "0.0.0.0",
        port      = 8000,
        reload    = True,
        log_level = "info",
    )
