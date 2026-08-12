"""
OrbitalMind — Load All 5 Demo Events into PostGIS
===================================================
Reads every event from backend/demo_data/events_manifest.json, then for each:
  1. Looks up the seeded event UUID in disaster_events (by disaster_type)
  2. Re-imports affected_zones from the demo GeoJSON file (idempotent)
  3. Calls calculate_priority_score(uuid, disaster_type) in PostgreSQL
  4. Prints progress with top-ranked zone

Usage
-----
    python scripts/load_all_demo_events.py
    python scripts/load_all_demo_events.py --db "postgresql://user:pass@host/db"
    python scripts/load_all_demo_events.py --dry-run   # validate files only

Pre-conditions
--------------
  - psql -U postgres -d orbitalmind -f db/schema.sql  (tables + seeded events)
  - python scripts/import_admin_zones.py               (14 Kerala districts)
  - osm2pgsql ... kerala-latest.osm.pbf                (planet_osm_* tables)
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

import psycopg2
import psycopg2.extras
psycopg2.extras.register_uuid()   # auto-cast UUID ↔ Python uuid.UUID

# ── Paths ─────────────────────────────────────────────────────────────────
_REPO = Path(__file__).resolve().parents[1]
_MANIFEST   = _REPO / "backend" / "demo_data" / "events_manifest.json"
_DEMO_DATA  = _REPO / "backend" / "demo_data"

_DEFAULT_DSN = "postgresql://postgres:postgres@localhost:5432/orbitalmind"

# Exclude these property keys from intensity_metadata (stored in dedicated columns)
_EXCLUDE_PROPS = {"confidence", "area_km2", "disaster_type"}


# ── helpers ────────────────────────────────────────────────────────────────

def get_geojson_path(event: dict) -> Path | None:
    """Resolve the GeoJSON file path for an event."""
    dtype    = event["disaster_type"]
    event_id = event["event_id"]

    # Manifest-provided path takes priority
    if "geojson_path" in event:
        p = _DEMO_DATA / event["geojson_path"]
        if p.exists():
            return p

    # Fallback: construct from convention
    subdir = _DEMO_DATA / dtype / event_id
    for name in ("flood_mask.geojson", "confidence_contours.geojson", "affected_zones.geojson"):
        p = subdir / name
        if p.exists():
            return p

    return None


def find_event_uuid(cur, disaster_type: str, date_start: str | None = None) -> str | None:
    """Look up the seeded event UUID by disaster_type (+optionally date_start)."""
    if date_start:
        cur.execute(
            "SELECT event_id FROM disaster_events "
            "WHERE disaster_type = %s AND date_start = %s LIMIT 1",
            (disaster_type, date_start),
        )
    else:
        cur.execute(
            "SELECT event_id FROM disaster_events WHERE disaster_type = %s LIMIT 1",
            (disaster_type,),
        )
    row = cur.fetchone()
    return str(row[0]) if row else None


def clear_event_data(cur, event_uuid: str) -> tuple[int, int]:
    """Delete existing affected_zones and priority_results for this event."""
    cur.execute("DELETE FROM priority_results WHERE event_id = %s::uuid", (event_uuid,))
    pr_deleted = cur.rowcount
    cur.execute("DELETE FROM affected_zones WHERE event_id = %s::uuid", (event_uuid,))
    az_deleted = cur.rowcount
    return az_deleted, pr_deleted


def load_geojson_zones(cur, event_uuid: str, disaster_type: str, geojson_path: Path) -> int:
    """Insert GeoJSON features into affected_zones. Returns row count."""
    data = json.loads(geojson_path.read_text(encoding="utf-8"))
    features = [f for f in data.get("features", []) if f.get("geometry")]

    inserted = 0
    for feat in features:
        props    = feat.get("properties") or {}
        geom_str = json.dumps(feat["geometry"])

        confidence = float(props.get("confidence", 0.5))
        confidence = max(0.0, min(1.0, confidence))

        area = props.get("area_km2")
        area = float(area) if area is not None else None

        meta = {k: v for k, v in props.items() if k not in _EXCLUDE_PROPS}

        cur.execute(
            """
            INSERT INTO affected_zones
                (event_id, disaster_type, geom,
                 confidence, area_km2, intensity_metadata, source)
            VALUES
                (%s::uuid, %s,
                 ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326),
                 %s, %s, %s::jsonb, 'demo')
            """,
            (
                event_uuid,
                disaster_type,
                geom_str,
                confidence,
                area,
                json.dumps(meta),
            ),
        )
        inserted += 1

    return inserted


def score_event(cur, event_uuid: str, disaster_type: str) -> list[dict]:
    """Call calculate_priority_score() and return ranked zones."""
    try:
        cur.execute(
            "SELECT zone_name, priority_score, priority_rank, "
            "hospitals_affected, schools_affected, population "
            "FROM calculate_priority_score(%s::uuid, %s) "
            "ORDER BY priority_rank",
            (event_uuid, disaster_type),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    except psycopg2.Error as e:
        msg = str(e).lower()
        if "planet_osm" in msg or "does not exist" in msg:
            return []           # OSM data not loaded yet — silent skip
        raise


# ── main ──────────────────────────────────────────────────────────────────

def run(dsn: str, dry_run: bool = False) -> None:
    print()
    print("=" * 70)
    print("  OrbitalMind — Demo Event Loader")
    print("=" * 70)

    # ── Load manifest ──────────────────────────────────────────────────
    if not _MANIFEST.exists():
        print(f"[ERROR] Manifest not found: {_MANIFEST}")
        print("        Run: python scripts/generate_mock_data.py")
        sys.exit(1)

    manifest  = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    events    = manifest.get("events", [])
    print(f"  Manifest: {len(events)} events found\n")

    if dry_run:
        print("  [DRY RUN] Validating GeoJSON paths only...")
        for ev in events:
            path = get_geojson_path(ev)
            status = "OK  " if path and path.exists() else "MISS"
            print(f"  [{status}] {ev['disaster_type']:12s} -> {path or '(not found)'}")
        print("\n  Dry run complete.\n")
        return

    # ── Database connection ───────────────────────────────────────────
    try:
        conn = psycopg2.connect(dsn)
        conn.autocommit = False
    except psycopg2.OperationalError as e:
        print(f"[ERROR] Cannot connect to database: {e}")
        print(f"        DSN: {dsn}")
        sys.exit(1)

    # ── Check PostGIS ─────────────────────────────────────────────────
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM pg_extension WHERE extname = 'postgis'"
        )
        if cur.fetchone()[0] == 0:
            print("[ERROR] PostGIS extension not installed in this database.")
            print("        Run: CREATE EXTENSION postgis;")
            conn.close()
            sys.exit(1)

    # ── Check planet_osm_point exists (OSM import) ────────────────────
    with conn.cursor() as cur:
        cur.execute(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_name = 'planet_osm_point')"
        )
        osm_loaded = cur.fetchone()[0]

    if not osm_loaded:
        print("  [WARN] planet_osm_point table not found.")
        print("         Infrastructure counts will be 0 — OSM import needed.")
        print("         Run: osm2pgsql -d orbitalmind -H localhost -U postgres kerala-latest.osm.pbf\n")

    # ── Process each event ────────────────────────────────────────────
    total_passed = 0
    total_failed = 0

    for ev in events:
        dtype    = ev.get("disaster_type", "")
        event_id = ev.get("event_id", "")
        name     = ev.get("display_name", event_id)
        date_str = ev.get("date_start")

        print(f"  ── {name} ({dtype}) {'─'*(50-len(name))}")

        # Resolve GeoJSON path
        geojson_path = get_geojson_path(ev)
        if not geojson_path:
            print(f"     [SKIP] GeoJSON file not found for {event_id}")
            total_failed += 1
            continue

        try:
            with conn.cursor() as cur:
                # ── Find event UUID ────────────────────────────────
                event_uuid = find_event_uuid(cur, dtype, date_str)
                if not event_uuid:
                    print(f"     [WARN] Event not in disaster_events table. Run: psql -f db/schema.sql")
                    total_failed += 1
                    continue
                print(f"     Event UUID : {event_uuid}")

                # ── Clear existing data ────────────────────────────
                az_del, pr_del = clear_event_data(cur, event_uuid)
                print(f"     Cleared    : {az_del} zones, {pr_del} priority results")

                # ── Insert affected zones ──────────────────────────
                n_zones = load_geojson_zones(cur, event_uuid, dtype, geojson_path)
                print(f"     Zones      : {n_zones} features loaded from {geojson_path.name}")

                # ── Score ──────────────────────────────────────────
                results = score_event(cur, event_uuid, dtype)

                if results:
                    top = results[0]
                    top_name  = top.get("zone_name", "Unknown")
                    top_score = float(top.get("priority_score") or 0)
                    top_hosp  = int(top.get("hospitals_affected") or 0)
                    print(
                        f"     Scored     : {len(results)} districts  "
                        f"| top zone: {top_name} ({top_score:.2f})"
                        f"  {top_hosp} hospitals"
                    )
                    print(f"     ✅ {name} ({dtype}) — {n_zones} zones imported, {len(results)} districts scored")
                else:
                    print(
                        f"     Scored     : 0 districts  (OSM data needed for spatial scoring)"
                    )
                    print(f"     ⚠️  {name} ({dtype}) — zones loaded but scoring skipped (no OSM)")

                conn.commit()
                total_passed += 1

        except Exception as exc:
            conn.rollback()
            print(f"     ❌ FAILED: {exc}")
            if "calculate_priority_score" in str(exc):
                print("        Hint: Run psql -f db/priority_scoring.sql to install the function.")
            traceback.print_exc()
            total_failed += 1

        print()

    conn.close()

    # ── Summary ───────────────────────────────────────────────────────
    print("=" * 70)
    print(f"  Results: {total_passed} passed  |  {total_failed} failed")
    if total_failed == 0:
        print("  ✅  All demo events loaded and scored successfully.")
    else:
        print("  ⚠️   Some events had issues — check output above.")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Load all OrbitalMind demo events into PostGIS"
    )
    parser.add_argument(
        "--db",
        default=_DEFAULT_DSN,
        help="PostgreSQL DSN (default: postgresql://postgres:postgres@localhost:5432/orbitalmind)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate GeoJSON paths without touching the database",
    )
    args = parser.parse_args()
    run(dsn=args.db, dry_run=args.dry_run)
