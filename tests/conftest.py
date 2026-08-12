"""
OrbitalMind — pytest configuration and shared fixtures.
=======================================================
Sets up a real asyncpg pool against the local test database and seeds
the additional rows needed to make all 5 disaster-type tests pass.

Environment
-----------
DATABASE_URL : str  (optional)
    Defaults to postgresql://postgres:postgres@localhost:5432/orbitalmind

Requirements
------------
    pip install pytest pytest-asyncio asyncpg anyio
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# OrbitalMind/ repo root on path
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import asyncpg
import pytest

_DSN = (
    os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/orbitalmind")
    .replace("postgresql+asyncpg://", "postgresql://")
)

# ── Scoring weights per disaster type (from docs/scoring_weights.md) ─────────
_WILDFIRE_WEIGHTS    = {"population": 0.35, "infra": 0.25, "access": 0.25, "intensity": 0.15}
_LANDSLIDE_WEIGHTS   = {"population": 0.30, "infra": 0.25, "access": 0.30, "intensity": 0.15}
_CYCLONE_WEIGHTS     = {"population": 0.30, "infra": 0.20, "access": 0.30, "intensity": 0.20}
_EARTHQUAKE_WEIGHTS  = {"population": 0.35, "infra": 0.30, "access": 0.20, "intensity": 0.15}

_SEED_RESULTS = [
    ("wildfire",   _WILDFIRE_WEIGHTS,   "Dehradun", 0.74, 3, 7, 1),
    ("landslide",  _LANDSLIDE_WEIGHTS,  "Shimla",   0.68, 2, 4, 3),
    ("cyclone",    _CYCLONE_WEIGHTS,    "Puri",     0.71, 5, 9, 2),
    ("earthquake", _EARTHQUAKE_WEIGHTS, "Bhuj",     0.63, 1, 3, 1),
]


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
async def db_pool():
    """Shared asyncpg pool for the whole test session."""
    pool = await asyncpg.create_pool(_DSN, statement_cache_size=0, min_size=1, max_size=4)
    yield pool
    await pool.close()


@pytest.fixture(scope="session")
async def seeded_pool(db_pool):
    """
    Seed one priority_result row per non-flood disaster type so that
    platform_summary and wildfire-weight tests pass.
    All inserted rows are deleted after the test session.
    """
    inserted_ids: list[str] = []

    async with db_pool.acquire() as conn:
        az_row = await conn.fetchrow(
            "SELECT zone_id FROM admin_zones WHERE state='Kerala' LIMIT 1"
        )
        if az_row is None:
            pytest.skip("No admin_zones — run: python scripts/setup_schema.py --password postgres")

        az_id = az_row["zone_id"]

        for dtype, weights, zone_name, score, hosp, sch, br in _SEED_RESULTS:
            ev_row = await conn.fetchrow(
                "SELECT event_id FROM disaster_events WHERE disaster_type=$1 LIMIT 1",
                dtype,
            )
            if ev_row is None:
                continue

            result_id = await conn.fetchval(
                """
                INSERT INTO priority_results
                    (event_id, admin_zone_id, disaster_type, zone_name,
                     priority_rank, priority_score,
                     hospitals_affected, schools_affected, bridges_affected,
                     scoring_weights)
                VALUES
                    ($1::uuid, $2::uuid, $3, $4, 1, $5, $6, $7, $8, $9::jsonb)
                RETURNING result_id
                """,
                str(ev_row["event_id"]), str(az_id),
                dtype, zone_name, score, hosp, sch, br,
                json.dumps(weights),
            )
            if result_id:
                inserted_ids.append(str(result_id))

    yield db_pool

    # Cleanup seeded rows
    if inserted_ids:
        async with db_pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM priority_results WHERE result_id = ANY($1::uuid[])",
                inserted_ids,
            )
