"""
OrbitalMind — SQLAlchemy 2.0 Async Database Connection
=======================================================
Provides:
  - ``engine``             Shared async SQLAlchemy engine (asyncpg driver)
  - ``AsyncSessionLocal``  Session factory for per-request sessions
  - ``get_db()``           FastAPI dependency that yields a managed AsyncSession
  - ``DbSession``          Annotated type alias for clean dependency injection
  - ``dispose_engine()``   Cleanup on app shutdown

Configuration
-------------
Set the ``DATABASE_URL`` environment variable.  Accepts both:
  - ``postgresql://user:pass@host/db``          (auto-converted to asyncpg)
  - ``postgresql+asyncpg://user:pass@host/db``  (used as-is)

Defaults to ``postgresql+asyncpg://postgres:postgres@localhost:5432/orbitalmind``.
"""
from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# ── DSN resolution ────────────────────────────────────────────────────────────

_DEFAULT_DSN = "postgresql+asyncpg://postgres:postgres@localhost:5432/orbitalmind"

DATABASE_URL: str = os.getenv("DATABASE_URL", _DEFAULT_DSN)

# Normalise: psycopg2 / raw postgres:// URLs → asyncpg dialect
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)
elif DATABASE_URL.startswith("postgresql://") and "+asyncpg" not in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

# ── Engine ────────────────────────────────────────────────────────────────────

engine = create_async_engine(
    DATABASE_URL,
    # Connection pool settings
    pool_size=5,           # Resident connections kept alive
    max_overflow=10,       # Extra connections allowed under load (total max: 15)
    pool_pre_ping=True,    # Validate connections before checkout (handles restarts)
    pool_recycle=3600,     # Recycle connections after 1 h (avoids stale TCP)
    echo=False,            # Set True to log all SQL statements during development
    # asyncpg-specific settings
    connect_args={
        "server_settings": {"jit": "off"},   # Disable JIT — improves PostGIS query plan stability
        "statement_cache_size": 0,            # Required for PgBouncer / transaction-mode pooling
    },
)

# ── Session factory ───────────────────────────────────────────────────────────

AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,  # Keep attributes accessible after commit
    autoflush=False,         # Flush explicitly — prevents surprise DB hits
    autocommit=False,
)

# ── FastAPI dependency ────────────────────────────────────────────────────────


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield a per-request ``AsyncSession``.

    Commits on success; rolls back and re-raises on any exception.
    Always closes the session (``finally`` block).

    Usage in a FastAPI route::

        @router.get("/events")
        async def list_events(db: DbSession) -> list[EventOut]:
            result = await db.execute(select(DisasterEvent))
            return result.scalars().all()
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# Annotated alias — avoids repeating Depends(get_db) in every route signature
DbSession = Annotated[AsyncSession, Depends(get_db)]


# ── Cleanup ───────────────────────────────────────────────────────────────────


async def dispose_engine() -> None:
    """Dispose the async engine connection pool.

    Call this in the FastAPI ``lifespan`` shutdown handler::

        @asynccontextmanager
        async def lifespan(app: FastAPI):
            yield
            await dispose_engine()
    """
    await engine.dispose()
