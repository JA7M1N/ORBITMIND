"""
OrbitalMind — GIS Service
==========================
Async spatial database service using asyncpg connection pool.

Responsibilities
----------------
- get_priority_zones()       Call PostgreSQL calculate_priority_score()
- import_affected_zones()    Load GeoJSON features into affected_zones table
- get_platform_summary()     Aggregate stats across all 5 disaster types
- get_event_zones_geojson()  Return zones as GeoJSON FeatureCollection

Architecture notes
------------------
- asyncpg is used for async/await I/O — required for FastAPI's async routes.
- A single shared pool (min=2, max=10) is created at app startup via connect()
  and closed at shutdown via disconnect(). Pass the same GISService instance
  to all routes (singleton pattern in main.py).
- UUID columns in asyncpg return Python uuid.UUID objects; we convert all to
  str for JSON serialisation before returning to callers.
- Coordinate system: affected_zones and admin_zones are EPSG:4326. PostGIS
  functions inside calculate_priority_score() handle the 4326↔3857 transforms
  for OSM data — callers never need to think about CRS.
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path
from typing import Any, Optional

# ── Repo root on path ────────────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# ── asyncpg import (graceful degradation) ────────────────────────────────────
try:
    import asyncpg  # type: ignore[import]
    _ASYNCPG_OK = True
except ImportError:
    asyncpg = None  # type: ignore[assignment]
    _ASYNCPG_OK = False

_DEFAULT_DSN = "postgresql://postgres:postgres@localhost:5432/orbitalmind"

# Valid disaster types
_DISASTER_TYPES = frozenset({"flood", "wildfire", "landslide", "cyclone", "earthquake"})


# ── Type helpers ─────────────────────────────────────────────────────────────

def _coerce_row(row: Any) -> dict[str, Any]:
    """Convert an asyncpg Record to a plain dict suitable for JSON.

    - ``uuid.UUID`` → ``str``
    - ``Decimal``   → ``float``
    - ``datetime``  → ISO 8601 string
    - ``str`` JSONB values → parsed dict/list
    """
    import decimal, datetime

    d: dict[str, Any] = dict(row)
    for k, v in d.items():
        if isinstance(v, uuid.UUID):
            d[k] = str(v)
        elif isinstance(v, decimal.Decimal):
            d[k] = float(v)
        elif isinstance(v, (datetime.datetime, datetime.date)):
            d[k] = v.isoformat()
        elif isinstance(v, str):
            # JSONB columns arrive as raw JSON strings in asyncpg
            stripped = v.strip()
            if stripped.startswith(("{", "[")):
                try:
                    d[k] = json.loads(stripped)
                except json.JSONDecodeError:
                    pass
    return d


# ── GISService ────────────────────────────────────────────────────────────────

class GISService:
    """Async PostGIS service for OrbitalMind spatial operations.

    Typical lifecycle (FastAPI)
    ---------------------------
    ::

        # main.py
        gis_svc = GISService()

        @asynccontextmanager
        async def lifespan(app):
            await gis_svc.connect()
            yield
            await gis_svc.disconnect()

    Then inject into routes via ``Depends`` or share directly.

    Example
    -------
    >>> import asyncio
    >>> svc = GISService()
    >>> zones = asyncio.run(svc.get_priority_zones("kerala_2018", "flood"))
    """

    def __init__(self, dsn: str = _DEFAULT_DSN) -> None:
        if not _ASYNCPG_OK:
            raise ImportError(
                "asyncpg is required for GISService.\n"
                "Install: pip install asyncpg"
            )
        self._dsn    = dsn
        self._pool: Optional["asyncpg.Pool"] = None

    # ── Pool lifecycle ────────────────────────────────────────────────────

    async def connect(self) -> None:
        """Create the asyncpg connection pool.

        Call once at FastAPI app startup via the lifespan context manager.

        Parameters
        ----------
        None — uses the DSN passed to ``__init__``.
        """
        self._pool = await asyncpg.create_pool(
            self._dsn,
            min_size        = 2,
            max_size        = 10,
            command_timeout = 120,   # 2 min — scoring query can be slow on first run
            statement_cache_size = 0,  # disable for compatibility with PgBouncer
        )

    async def disconnect(self) -> None:
        """Close the connection pool gracefully.

        Call at FastAPI app shutdown.
        """
        if self._pool:
            await self._pool.close()
            self._pool = None

    async def _pool_or_connect(self) -> "asyncpg.Pool":
        """Return pool, creating it lazily if not yet initialised."""
        if self._pool is None:
            await self.connect()
        return self._pool

    # ── Helpers ───────────────────────────────────────────────────────────

    async def _resolve_event_id(self, event_id: str) -> uuid.UUID:
        """Resolve event_id to a UUID.

        Accepts:
        - UUID string: ``"550e8400-e29b-41d4-a716-446655440000"``
        - Event slug:  ``"kerala_2018"`` or ``"kerala-2018"``

        Parameters
        ----------
        event_id : str
            UUID or slug.

        Returns
        -------
        uuid.UUID
            The event's primary key.

        Raises
        ------
        ValueError
            If the slug matches no event in disaster_events.
        """
        # Try parsing as UUID first
        try:
            return uuid.UUID(event_id)
        except ValueError:
            pass

        slug = event_id.replace("-", "_").lower()
        pool = await self._pool_or_connect()

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT event_id FROM disaster_events
                WHERE
                    lower(replace(region, ' ', '_')) || '_'
                    || EXTRACT(YEAR FROM date_start)::TEXT = $1
                    OR lower(replace(display_name, ' ', '_')) LIKE '%' || $1 || '%'
                ORDER BY date_start DESC
                LIMIT 1
                """,
                slug,
            )

        if row is None:
            raise ValueError(
                f"Event '{event_id}' not found in disaster_events. "
                "Use the UUID from SELECT event_id, display_name FROM disaster_events;"
            )
        return row["event_id"]

    # ── 1. Priority Zones ─────────────────────────────────────────────────

    async def get_priority_zones(
        self,
        event_id:     str,
        disaster_type: str,
    ) -> list[dict[str, Any]]:
        """Call ``calculate_priority_score()`` and return ranked admin zones.

        Runs the full infrastructure overlay + scoring pipeline inside
        PostgreSQL (no Python-side computation).  Results are also
        written to ``priority_results`` as a side-effect.

        Parameters
        ----------
        event_id : str
            UUID or slug (e.g. ``"kerala_2018"``).
        disaster_type : str
            One of: ``flood``, ``wildfire``, ``landslide``, ``cyclone``,
            ``earthquake``.

        Returns
        -------
        list[dict]
            Ranked zones with keys: ``zone_name``, ``population``,
            ``hospitals_affected``, ``schools_affected``,
            ``bridges_at_risk``, ``roads_disrupted_pct``,
            ``population_score``, ``infra_score``, ``access_score``,
            ``intensity_score``, ``priority_score``, ``priority_rank``.

        Raises
        ------
        ValueError
            If ``disaster_type`` is invalid or event not found.
        """
        dtype = disaster_type.lower().strip()
        if dtype not in _DISASTER_TYPES:
            raise ValueError(
                f"Unknown disaster_type '{dtype}'. "
                f"Valid: {sorted(_DISASTER_TYPES)}"
            )

        event_uuid = await self._resolve_event_id(event_id)
        pool       = await self._pool_or_connect()

        async with pool.acquire() as conn:
            # ── Primary: full PostGIS scoring pipeline ─────────────────────
            try:
                rows = await conn.fetch(
                    "SELECT * FROM calculate_priority_score($1, $2)",
                    event_uuid,
                    dtype,
                )
                if rows:
                    return [_coerce_row(r) for r in rows]
                # 0 rows = admin_zones don't overlap — fall through to pre-computed
            except Exception as _exc:  # noqa: BLE001
                # PostGIS not installed, planet_osm_* missing, or function missing
                import logging
                logging.getLogger(__name__).warning(
                    "calculate_priority_score() failed (%s) — "
                    "falling back to pre-computed priority_results", _exc
                )

            # ── Fallback: query pre-computed priority_results directly ───────
            rows = await conn.fetch(
                """
                SELECT
                    pr.result_id,
                    pr.admin_zone_id,
                    pr.zone_name,
                    adm.population,
                    pr.hospitals_affected,
                    pr.schools_affected,
                    pr.bridges_affected,
                    0.0::FLOAT                  AS roads_disrupted_pct,
                    pr.population_score,
                    pr.infra_score,
                    pr.access_score,
                    pr.intensity_score,
                    pr.priority_score,
                    pr.priority_rank,
                    pr.scoring_weights::TEXT    AS scoring_weights,
                    pr.disaster_type
                FROM priority_results pr
                LEFT JOIN admin_zones adm ON pr.admin_zone_id = adm.zone_id
                WHERE pr.event_id = $1
                ORDER BY pr.priority_rank
                """,
                event_uuid,
            )

        return [_coerce_row(r) for r in rows]

    # ── 2. Import Affected Zones ──────────────────────────────────────────

    async def import_affected_zones(
        self,
        event_id:     str,
        disaster_type: str,
        geojson_path: str,
    ) -> int:
        """Read a GeoJSON file and insert its features into ``affected_zones``.

        Deletes any existing zones for this event before inserting so the
        operation is idempotent.  Each GeoJSON Feature becomes one row.

        Properties mapping
        ------------------
        - ``confidence``         → ``affected_zones.confidence``
        - ``area_km2``           → ``affected_zones.area_km2``
        - ``disaster_type``      → discarded (use parameter instead)
        - All other properties   → ``affected_zones.intensity_metadata`` (JSONB)

        Parameters
        ----------
        event_id : str
            UUID or slug.
        disaster_type : str
            Module routing key.
        geojson_path : str
            Absolute or relative path to the GeoJSON file.

        Returns
        -------
        int
            Number of features inserted.

        Raises
        ------
        FileNotFoundError
            If the GeoJSON file does not exist.
        ValueError
            If disaster_type is invalid.
        """
        dtype = disaster_type.lower().strip()
        if dtype not in _DISASTER_TYPES:
            raise ValueError(f"Unknown disaster_type '{dtype}'.")

        path = Path(geojson_path)
        if not path.exists():
            raise FileNotFoundError(f"GeoJSON not found: {path}")

        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)

        features: list[dict] = data.get("features", [])
        if not features:
            return 0

        event_uuid = await self._resolve_event_id(event_id)
        pool       = await self._pool_or_connect()

        _EXCLUDE = {"confidence", "area_km2", "disaster_type"}

        async with pool.acquire() as conn:
            # Clear existing zones for idempotency
            deleted = await conn.execute(
                "DELETE FROM affected_zones WHERE event_id = $1",
                event_uuid,
            )

            inserted = 0
            for feat in features:
                props    = feat.get("properties") or {}
                geom_str = json.dumps(feat["geometry"])

                confidence = float(props.get("confidence", 0.5))
                confidence = max(0.0, min(1.0, confidence))

                area = props.get("area_km2")
                area = float(area) if area is not None else None

                intensity_meta = {k: v for k, v in props.items() if k not in _EXCLUDE}

                await conn.execute(
                    """
                    INSERT INTO affected_zones
                        (event_id, disaster_type, geom,
                         confidence, area_km2, intensity_metadata, source)
                    VALUES
                        ($1, $2,
                         ST_SetSRID(ST_GeomFromGeoJSON($3), 4326),
                         $4, $5, $6::jsonb, 'demo')
                    """,
                    event_uuid,
                    dtype,
                    geom_str,
                    confidence,
                    area,
                    json.dumps(intensity_meta),
                )
                inserted += 1

        return inserted

    # ── 3. Platform Summary ───────────────────────────────────────────────

    async def get_platform_summary(self) -> dict[str, Any]:
        """Return aggregate statistics across all 5 disaster modules.

        Queries ``disaster_events``, ``affected_zones``, and
        ``priority_results`` to build a dashboard-ready summary.

        Returns
        -------
        dict
            ::

                {
                    "total_events":       5,
                    "total_zones":        31,
                    "total_results":      14,
                    "admin_zones_loaded": 14,
                    "by_disaster_type": [
                        {
                            "disaster_type":      "flood",
                            "events":             1,
                            "zones_scored":       8,
                            "population_at_risk": 3301427,
                            "last_event":         "2018-08-01",
                            "last_scored":        "2024-08-08T17:40:00+00:00"
                        },
                        ...
                    ]
                }
        """
        pool = await self._pool_or_connect()

        async with pool.acquire() as conn:
            event_rows = await conn.fetch(
                """
                SELECT
                    disaster_type,
                    COUNT(*)::INTEGER           AS event_count,
                    MAX(date_start)             AS latest_event
                FROM disaster_events
                GROUP BY disaster_type
                ORDER BY event_count DESC
                """
            )

            pr_rows = await conn.fetch(
                """
                SELECT
                    pr.disaster_type,
                    COUNT(DISTINCT pr.result_id)::INTEGER   AS zones_scored,
                    COALESCE(SUM(adm.population), 0)::BIGINT AS population_at_risk,
                    MAX(pr.created_at)                       AS last_scored
                FROM priority_results pr
                LEFT JOIN admin_zones adm ON pr.admin_zone_id = adm.zone_id
                GROUP BY pr.disaster_type
                """
            )

            totals = await conn.fetchrow(
                """
                SELECT
                    (SELECT COUNT(*) FROM disaster_events)   AS total_events,
                    (SELECT COUNT(*) FROM affected_zones)    AS total_zones,
                    (SELECT COUNT(*) FROM priority_results)  AS total_results,
                    (SELECT COUNT(*) FROM admin_zones)       AS admin_zones_loaded
                """
            )

        event_map = {r["disaster_type"]: _coerce_row(r) for r in event_rows}
        pr_map    = {r["disaster_type"]: _coerce_row(r) for r in pr_rows}

        by_type = []
        for dt in ["flood", "wildfire", "landslide", "cyclone", "earthquake"]:
            em = event_map.get(dt, {})
            pm = pr_map.get(dt, {})
            by_type.append({
                "disaster_type":      dt,
                "events":             int(em.get("event_count", 0)),
                "zones_scored":       int(pm.get("zones_scored", 0)),
                "population_at_risk": int(pm.get("population_at_risk", 0)),
                "last_event":         em.get("latest_event"),
                "last_scored":        pm.get("last_scored"),
            })

        return {
            "total_events":       int(totals["total_events"]),
            "total_zones":        int(totals["total_zones"]),
            "total_results":      int(totals["total_results"]),
            "admin_zones_loaded": int(totals["admin_zones_loaded"]),
            "by_disaster_type":   by_type,
        }

    # ── 4. Event Zones as GeoJSON ─────────────────────────────────────────

    async def get_event_zones_geojson(
        self,
        event_id: str,
    ) -> dict[str, Any]:
        """Return all affected zones for an event as a GeoJSON FeatureCollection.

        Each feature includes the raw geometry plus all available properties:
        confidence, area, intensity_metadata fields, and (if scored)
        priority_score, priority_rank, hospitals_affected, district_name.

        Features are ordered by priority_rank (lowest = highest priority first).

        Parameters
        ----------
        event_id : str
            UUID or slug.

        Returns
        -------
        dict
            GeoJSON FeatureCollection ready for the MapLibre GL frontend.

        Raises
        ------
        ValueError
            If event not found.
        """
        event_uuid = await self._resolve_event_id(event_id)
        pool       = await self._pool_or_connect()

        async with pool.acquire() as conn:
            # ── Primary: full PostGIS query with ST_AsGeoJSON + ST_Intersects ──
            try:
                rows = await conn.fetch(
                    """
                    SELECT
                        az.zone_id,
                        az.disaster_type,
                        az.confidence,
                        az.area_km2,
                        az.intensity_metadata::TEXT AS intensity_meta_str,
                        az.source,
                        ST_AsGeoJSON(az.geom, 6)    AS geometry_json,
                        NULL::TEXT                  AS geometry_text,
                        pr.priority_score,
                        pr.priority_rank,
                        pr.hospitals_affected,
                        pr.schools_affected,
                        pr.bridges_affected,
                        adm.name                    AS district_name,
                        adm.population              AS district_population
                    FROM affected_zones az
                    LEFT JOIN priority_results pr
                        ON az.event_id = pr.event_id
                        AND pr.admin_zone_id IN (
                            SELECT adm2.zone_id FROM admin_zones adm2
                            WHERE ST_Intersects(az.geom, adm2.geom)
                            LIMIT 1
                        )
                    LEFT JOIN admin_zones adm ON pr.admin_zone_id = adm.zone_id
                    WHERE az.event_id = $1
                    ORDER BY COALESCE(pr.priority_rank, 9999), az.confidence DESC
                    """,
                    event_uuid,
                )
                use_geom_text = False
            except Exception as _exc:  # noqa: BLE001
                # PostGIS not available — fall back to geom_text column
                import logging
                logging.getLogger(__name__).warning(
                    "get_event_zones_geojson() PostGIS query failed (%s) — "
                    "using geom_text fallback", _exc
                )
                rows = await conn.fetch(
                    """
                    SELECT
                        az.zone_id,
                        az.disaster_type,
                        az.confidence,
                        az.area_km2,
                        az.intensity_metadata::TEXT AS intensity_meta_str,
                        az.source,
                        NULL::TEXT                  AS geometry_json,
                        az.geom_text                AS geometry_text,
                        NULL::FLOAT                 AS priority_score,
                        NULL::INTEGER               AS priority_rank,
                        NULL::INTEGER               AS hospitals_affected,
                        NULL::INTEGER               AS schools_affected,
                        NULL::INTEGER               AS bridges_affected,
                        NULL::TEXT                  AS district_name,
                        NULL::BIGINT                AS district_population
                    FROM affected_zones az
                    WHERE az.event_id = $1
                    ORDER BY az.confidence DESC
                    """,
                    event_uuid,
                )
                use_geom_text = True

        features: list[dict] = []
        for row in rows:
            props: dict[str, Any] = {
                "zone_id":       str(row["zone_id"]),
                "disaster_type": row["disaster_type"],
                "confidence":    float(row["confidence"] or 0),
                "source":        row["source"],
            }

            if row["area_km2"] is not None:
                props["area_km2"] = float(row["area_km2"])
            if row["priority_score"] is not None:
                props["priority_score"] = float(row["priority_score"])
                props["priority_rank"]  = int(row["priority_rank"])
            if row["hospitals_affected"] is not None:
                props["hospitals_affected"] = int(row["hospitals_affected"])
            if row["schools_affected"] is not None:
                props["schools_affected"] = int(row["schools_affected"])
            if row["district_name"]:
                props["district_name"]       = row["district_name"]
                props["district_population"] = int(row["district_population"] or 0)

            # Merge intensity_metadata fields
            if row["intensity_meta_str"]:
                try:
                    meta = json.loads(row["intensity_meta_str"])
                    if isinstance(meta, dict):
                        props.update(meta)
                except json.JSONDecodeError:
                    pass

            # Resolve geometry
            geom_src = row["geometry_text"] if use_geom_text else row["geometry_json"]
            if geom_src:
                try:
                    geometry = json.loads(geom_src)
                except (json.JSONDecodeError, TypeError):
                    geometry = None
            else:
                geometry = None

            features.append({
                "type":       "Feature",
                "geometry":   geometry,
                "properties": props,
            })

        return {
            "type":     "FeatureCollection",
            "features": features,
        }
