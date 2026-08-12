"""
OrbitalMind — GIS Service Test Suite
======================================
Tests the five core guarantees of ``GISService``:

  1. get_priority_zones("kerala_2018", "flood")  returns ≥ 5 zones
  2. All priority_score values are in [0.0, 1.0]
  3. Wildfire event has scoring_weights["population"] == 0.35
  4. get_platform_summary() contains all 5 disaster types
  5. get_event_zones_geojson() features have valid GeoJSON geometry

Requirements
------------
  - PostgreSQL running on localhost:5432, database: orbitalmind
  - python scripts/setup_schema.py --password postgres   (seeds tables)
  - pip install pytest pytest-asyncio asyncpg anyio

Run
---
  pytest tests/test_gis_service.py -v
  pytest tests/test_gis_service.py -v --tb=short   (concise on failures)
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import asyncpg
import pytest

# ── Path setup ────────────────────────────────────────────────────────────────
_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from backend.services.gis_service import GISService

# ── Helpers ───────────────────────────────────────────────────────────────────

_DSN = (
    os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/orbitalmind")
    .replace("postgresql+asyncpg://", "postgresql://")
)

_ASYNCPG_DSN = _DSN  # asyncpg uses postgresql:// (not +asyncpg)
_SA_DSN = _DSN.replace("postgresql://", "postgresql+asyncpg://")  # SQLAlchemy


async def _make_service() -> GISService:
    """Create and connect a GISService instance."""
    svc = GISService(dsn=_ASYNCPG_DSN)
    await svc.connect()
    return svc


# ── Test 1: get_priority_zones returns ≥ 5 zones for Kerala flood ─────────────

@pytest.mark.asyncio
async def test_priority_zones_count(seeded_pool: asyncpg.Pool) -> None:
    """
    get_priority_zones("kerala_2018", "flood") must return at least 5 districts.

    The Kerala 2018 event has 8 pre-computed priority_results rows (seeded by
    setup_schema.py).  The service should return all 8 via its fallback path
    when PostGIS is not yet installed.

    Validates
    ---------
    - len(zones) >= 5
    - Each result has ``zone_name`` and ``priority_score`` fields
    - ``priority_rank`` starts at 1
    """
    svc = await _make_service()
    try:
        zones = await svc.get_priority_zones("kerala_2018", "flood")
    finally:
        await svc.disconnect()

    assert len(zones) >= 5, (
        f"Expected ≥ 5 priority zones, got {len(zones)}. "
        "Run: python scripts/setup_schema.py --password postgres"
    )
    # Structural checks
    for z in zones:
        assert "zone_name" in z, f"Missing 'zone_name' in zone: {z}"
        assert "priority_score" in z, f"Missing 'priority_score' in zone: {z}"

    # Rank 1 should be first
    ranks = [z.get("priority_rank") for z in zones if z.get("priority_rank") is not None]
    if ranks:
        assert min(ranks) == 1, f"Lowest rank should be 1, got {min(ranks)}"


# ── Test 2: All priority_score values are in [0, 1] ──────────────────────────

@pytest.mark.asyncio
async def test_priority_scores_in_range(seeded_pool: asyncpg.Pool) -> None:
    """
    All priority_score values returned by get_priority_zones must be in [0.0, 1.0].

    The scoring formula is a weighted sum of normalised component scores,
    each in [0, 1], so the composite is also guaranteed to be in [0, 1].
    A value outside this range indicates a weight configuration bug.

    Validates
    ---------
    - 0.0 <= priority_score <= 1.0  for every zone
    - No None / null scores
    """
    svc = await _make_service()
    try:
        zones = await svc.get_priority_zones("kerala_2018", "flood")
    finally:
        await svc.disconnect()

    assert zones, "No zones returned — re-run setup_schema.py"

    for z in zones:
        score = z.get("priority_score")
        assert score is not None, f"None priority_score in zone {z.get('zone_name')}"
        score_f = float(score)
        assert 0.0 <= score_f <= 1.0, (
            f"priority_score={score_f} out of [0,1] for zone={z.get('zone_name')}"
        )


# ── Test 3: Wildfire scoring_weights has population = 0.35 ───────────────────

@pytest.mark.asyncio
async def test_wildfire_scoring_weights(seeded_pool: asyncpg.Pool) -> None:
    """
    The wildfire module uses population weight = 0.35 (not 0.40 as for flood).

    In the wildfire scoring model, terrain + access factors (fire spread vectors)
    are weighted more heavily than population alone, so population drops from
    0.40 → 0.35 and access rises to 0.25.  This test guards against weight
    regressions when the scoring function is updated.

    Validates
    ---------
    - wildfire priority_results rows exist (seeded by conftest.py)
    - scoring_weights["population"] == 0.35  (within float tolerance)
    - scoring_weights["infra"]      == 0.25
    - weights sum to 1.0
    """
    # Open a fresh connection on THIS test's event loop to avoid pool/loop mismatch
    conn = await asyncpg.connect(_ASYNCPG_DSN, statement_cache_size=0)
    try:
        row = await conn.fetchrow(
            """
            SELECT scoring_weights::TEXT AS sw
            FROM priority_results
            WHERE disaster_type = 'wildfire'
            LIMIT 1
            """
        )
    finally:
        await conn.close()

    assert row is not None, (
        "No wildfire priority_results found. "
        "Ensure conftest seeded_pool fixture ran (it should auto-run via dependency)."
    )

    sw_raw = row["sw"]
    assert sw_raw, "scoring_weights is NULL for wildfire row"

    weights: dict[str, float] = json.loads(sw_raw)

    assert "population" in weights, f"'population' key missing from weights: {weights}"
    assert abs(weights["population"] - 0.35) < 1e-6, (
        f"wildfire population weight = {weights['population']}, expected 0.35"
    )

    if "infra" in weights:
        assert abs(weights["infra"] - 0.25) < 1e-6, (
            f"wildfire infra weight = {weights['infra']}, expected 0.25"
        )

    total = sum(weights.values())
    assert abs(total - 1.0) < 1e-5, (
        f"Wildfire weights do not sum to 1.0 (got {total:.6f}): {weights}"
    )


# ── Test 4: get_platform_summary contains all 5 disaster types ───────────────

@pytest.mark.asyncio
async def test_platform_summary_all_types(seeded_pool: asyncpg.Pool) -> None:
    """
    get_platform_summary() must return a dict containing all 5 disaster types.

    The ``by_disaster_type`` key should have exactly 5 entries — one per module.
    After seeding in conftest, each disaster type has at least one event and one
    priority_result row, so all 5 should appear with events > 0.

    Validates
    ---------
    - Summary has keys: total_events, total_zones, total_results, by_disaster_type
    - len(by_disaster_type) == 5
    - All 5 types present: flood, wildfire, landslide, cyclone, earthquake
    - total_events >= 5  (one per module)
    """
    svc = await _make_service()
    try:
        summary: dict[str, Any] = await svc.get_platform_summary()
    finally:
        await svc.disconnect()

    # Top-level structure
    required_keys = {"total_events", "total_zones", "total_results", "by_disaster_type"}
    missing = required_keys - summary.keys()
    assert not missing, f"Summary missing keys: {missing}"

    assert int(summary["total_events"]) >= 5, (
        f"total_events={summary['total_events']} — expected ≥ 5"
    )

    by_type: list[dict] = summary["by_disaster_type"]
    assert len(by_type) == 5, (
        f"Expected 5 disaster types in summary, got {len(by_type)}: "
        f"{[d['disaster_type'] for d in by_type]}"
    )

    expected_types = {"flood", "wildfire", "landslide", "cyclone", "earthquake"}
    found_types    = {d["disaster_type"] for d in by_type}
    missing_types  = expected_types - found_types
    assert not missing_types, f"Missing disaster types in summary: {missing_types}"

    # Each type should have at least 1 event
    for entry in by_type:
        assert entry["events"] >= 1, (
            f"disaster_type={entry['disaster_type']} has events=0 — seed data missing"
        )


# ── Test 5: GeoJSON geometry is structurally valid ────────────────────────────

@pytest.mark.asyncio
async def test_geojson_geometry_structure(seeded_pool: asyncpg.Pool) -> None:
    """
    get_event_zones_geojson() features must have valid GeoJSON geometry objects.

    The affected_zones table stores geometries as GeoJSON strings (geom_text)
    in the fallback schema.  This test verifies that:
    - The FeatureCollection structure is correct
    - Each feature has a valid GeoJSON geometry dict
    - geometry["type"] is a recognised GeoJSON geometry type
    - geometry["coordinates"] exists and is a non-empty list

    Validates (GeoJSON spec RFC 7946)
    ---------
    - fc["type"] == "FeatureCollection"
    - len(fc["features"]) >= 1
    - feature["type"] == "Feature"
    - feature["geometry"]["type"] in VALID_TYPES
    - feature["geometry"]["coordinates"] is non-empty
    - feature["properties"]["confidence"] in [0, 1]
    """
    VALID_GEOM_TYPES = {
        "Point", "MultiPoint",
        "LineString", "MultiLineString",
        "Polygon", "MultiPolygon",
        "GeometryCollection",
    }

    svc = await _make_service()
    try:
        fc: dict[str, Any] = await svc.get_event_zones_geojson("kerala_2018")
    finally:
        await svc.disconnect()

    # FeatureCollection root
    assert fc.get("type") == "FeatureCollection", (
        f"Expected type='FeatureCollection', got {fc.get('type')!r}"
    )
    features: list[dict] = fc.get("features", [])
    assert len(features) >= 1, (
        "No features in FeatureCollection — affected_zones may be empty"
    )

    for i, feat in enumerate(features):
        # Feature wrapper
        assert feat.get("type") == "Feature", (
            f"Feature[{i}] type={feat.get('type')!r}, expected 'Feature'"
        )
        assert "properties" in feat, f"Feature[{i}] missing 'properties'"

        geom = feat.get("geometry")
        assert geom is not None, (
            f"Feature[{i}] geometry is None — geom_text may be malformed"
        )
        assert isinstance(geom, dict), (
            f"Feature[{i}] geometry should be dict, got {type(geom)}"
        )
        assert geom.get("type") in VALID_GEOM_TYPES, (
            f"Feature[{i}] geometry type={geom.get('type')!r} not a valid GeoJSON type"
        )
        coords = geom.get("coordinates")
        assert coords is not None and len(coords) > 0, (
            f"Feature[{i}] geometry.coordinates is empty"
        )

        # Properties: confidence should be numeric and in [0, 1]
        conf = feat["properties"].get("confidence")
        if conf is not None:
            assert 0.0 <= float(conf) <= 1.0, (
                f"Feature[{i}] confidence={conf} out of [0, 1]"
            )
