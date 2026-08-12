"""
OrbitalMind — Tasks Router
============================
GET /api/tasks         → list all tracked inference tasks (newest-last)
GET /api/tasks/{id}    → status of a single background inference task

Used for polling-based progress tracking.  For push-based updates,
subscribe to WS /api/ws/progress/{task_id} instead.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.services.ml_service import MLService

router = APIRouter(prefix="/tasks", tags=["Tasks"])
_svc   = MLService()


@router.get(
    "",
    summary      = "List all inference tasks",
    response_description = "All InferenceStatus records (newest-last)",
)
async def list_tasks() -> list[dict]:
    """Return status records for every tracked background inference task.

    Tasks are never evicted during the process lifetime, so this list
    grows over time.  Useful for an admin dashboard.
    """
    return _svc.list_tasks()


@router.get(
    "/{task_id}",
    summary      = "Poll a single inference task",
    response_description = "InferenceStatus for the given task_id",
)
async def get_task(task_id: str) -> dict:
    """Return the current status of a background inference task.

    Poll this endpoint every second, or subscribe to
    ``WS /api/ws/progress/{task_id}`` for push-based updates.

    Status lifecycle
    ----------------
    ``pending`` → ``running`` → ``complete``
                              → ``error``

    Parameters
    ----------
    task_id : str
        UUID returned by ``POST /api/analyze`` with ``demo_mode=False``.

    Raises
    ------
    404
        If ``task_id`` is not found in the task store.
    """
    try:
        return _svc.get_task_status(task_id)
    except KeyError:
        raise HTTPException(
            status_code = 404,
            detail      = f"Task '{task_id}' not found. "
                          "It may have never been created or the server was restarted.",
        )
