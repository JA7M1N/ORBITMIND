"""
OrbitalMind — WebSocket Progress Router v2
============================================
WS /api/ws/progress?task_id=X

Streams real-time inference progress messages to the frontend every 500 ms.
The frontend connects immediately after receiving a task_id from POST /api/analyze.

Protocol
--------
Server sends JSON messages at 500 ms intervals:

  {
    "task_id":      "<uuid>",
    "progress":     45.0,          // 0–100 %
    "status":       "running",     // running | complete | error
    "message":      "Running Attention U-Net flood segmentation...",
    "disaster_type": "flood",
    "result":       null           // full DetectionResult when complete
  }

Connection closed by server when status reaches "complete" or "error".
Client should attempt reconnect on unexpected close during active tasks.

Example (JavaScript / React)
----------------------------
  const ws = new WebSocket(
    `ws://localhost:8000/api/ws/progress?task_id=${taskId}`
  );
  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    setProgress(msg.progress);
    setStage(msg.message);
    if (msg.status === 'complete') {
      setZones(msg.result.affected_zones_geojson);
      setPriority(msg.result.priority_zones);
    }
  };
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from backend.config import settings

router = APIRouter(tags=["WebSocket"])

# Push interval — 500 ms gives smooth progress animation in the frontend
_INTERVAL: float = 0.5


@router.websocket("/ws/progress")
async def ws_progress(
    websocket: WebSocket,
    task_id: str = Query(..., description="Task UUID from POST /api/analyze"),
) -> None:
    """Stream real-time progress for a background analysis task.

    Sends one JSON message per 500 ms until the task reaches
    ``complete`` or ``error``, then closes the connection.

    Parameters
    ----------
    task_id : str
        UUID returned by ``POST /api/analyze``.
    """
    # Import here to avoid circular import; task_progress lives in analyze module
    from backend.routers.analyze import task_progress

    await websocket.accept()

    try:
        # ── Wait up to 10 s for the task to appear (startup race) ─────────
        for _ in range(20):
            if task_id in task_progress:
                break
            await asyncio.sleep(0.5)
        else:
            await websocket.send_json({
                "error":    f"Task '{task_id}' not found.",
                "task_id":  task_id,
                "status":   "error",
                "progress": 0,
                "message":  "Task not found — check task_id.",
            })
            return

        # ── Stream progress until terminal state ──────────────────────────
        while True:
            state = task_progress.get(task_id)
            if state is None:
                await websocket.send_json({
                    "error":   "Task disappeared (server restart?).",
                    "task_id": task_id,
                    "status":  "error",
                    "progress": 0,
                })
                break

            await websocket.send_json({
                "task_id":       task_id,
                "progress":      state.get("progress", 0),
                "status":        state.get("status", "running"),
                "message":       state.get("message", ""),
                "disaster_type": state.get("disaster_type", ""),
                "event_id":      state.get("event_id", ""),
                "result":        state.get("result"),    # None until complete
                "error":         state.get("error"),
            })

            if state.get("status") in ("complete", "error"):
                break

            await asyncio.sleep(_INTERVAL)

    except WebSocketDisconnect:
        # Client navigated away — nothing to do
        pass
    except Exception as exc:
        try:
            detail = f"Server error: {exc}" if settings.DEMO_MODE else "Internal server error."
            await websocket.send_json({
                "error":    detail,
                "task_id":  task_id,
                "status":   "error",
                "progress": 0,
            })
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


# ── Keep backward compat for existing /ws/progress/{task_id} path ─────────────

@router.websocket("/ws/progress/{task_id}")
async def ws_progress_path(websocket: WebSocket, task_id: str) -> None:
    """Backward-compatible path param version — delegates to query param handler."""
    from backend.routers.analyze import task_progress
    await websocket.accept()

    try:
        for _ in range(20):
            if task_id in task_progress:
                break
            await asyncio.sleep(0.5)
        else:
            await websocket.send_json({"error": f"Task '{task_id}' not found.", "status": "error"})
            return

        while True:
            state = task_progress.get(task_id)
            if not state:
                break
            await websocket.send_json({
                "task_id":  task_id,
                "progress": state.get("progress", 0),
                "status":   state.get("status", "running"),
                "message":  state.get("message", ""),
                "disaster_type": state.get("disaster_type", ""),
                "result":   state.get("result"),
                "error":    state.get("error"),
            })
            if state.get("status") in ("complete", "error"):
                break
            await asyncio.sleep(_INTERVAL)
    except WebSocketDisconnect:
        pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
