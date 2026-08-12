"""
OrbitalMind — Full DB Bootstrap
================================
One script to run everything in order:
  1. Create orbitalmind DB (if missing)
  2. Enable PostGIS + uuid-ossp
  3. Run db/schema.sql  (tables + seeded events)
  4. Install db/priority_scoring.sql (plpgsql function)
  5. Load all 5 demo events + affected_zones
  6. Score all events (calculate_priority_score)
  7. Validate Kerala 2018

Usage
-----
    python scripts/bootstrap_db.py
    python scripts/bootstrap_db.py --host localhost --port 5432 --user postgres --password postgres
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

import psycopg2
import psycopg2.extras
psycopg2.extras.register_uuid()

_REPO = Path(__file__).resolve().parents[1]

# ── helpers ────────────────────────────────────────────────────────────────

def connect(host, port, user, password, dbname="postgres"):
    return psycopg2.connect(
        host=host, port=port, user=user, password=password, dbname=dbname
    )

def banner(msg):
    print(f"\n{'='*65}\n  {msg}\n{'='*65}")

def ok(msg):   print(f"  [  OK  ]  {msg}")
def warn(msg): print(f"  [ WARN ]  {msg}")
def fail(msg): print(f"  [ FAIL ]  {msg}")

def run_sql_file(conn, path: Path, label: str):
    sql = path.read_text(encoding="utf-8")
    # Strip psql meta-commands (\echo, \set, etc.) — psycopg2 can't handle them
    lines = []
    for line in sql.splitlines():
        s = line.strip()
        if s.startswith("\\"):
            continue           # skip psql-only directives
        lines.append(line)
    clean_sql = "\n".join(lines)
    with conn.cursor() as cur:
        cur.execute(clean_sql)
    conn.commit()
    ok(f"{label} executed")


def get_geojson_path(event: dict) -> Path | None:
    demo_data = _REPO / "backend" / "demo_data"
    dtype    = event["disaster_type"]
    event_id = event["event_id"]
    if "geojson_path" in event:
        p = demo_data / event["geojson_path"]
        if p.exists():
            return p
    subdir = demo_data / dtype / event_id
    for name in ("flood_mask.geojson", "confidence_contours.geojson", "affected_zones.geojson"):
        p = subdir / name
        if p.exists():
            return p
    return None

_EXCLUDE_PROPS = {"confidence", "area_km2", "disaster_type"}

def load_zones(cur, event_uuid, dtype, geojson_path):
    data     = json.loads(geojson_path.read_text(encoding="utf-8"))
    features = [f for f in data.get("features", []) if f.get("geometry")]
    inserted = 0
    for feat in features:
        props    = feat.get("properties") or {}
        geom_str = json.dumps(feat["geometry"])
        conf     = max(0.0, min(1.0, float(props.get("confidence", 0.5))))
        area     = props.get("area_km2")
        area     = float(area) if area is not None else None
        meta     = {k: v for k, v in props.items() if k not in _EXCLUDE_PROPS}
        cur.execute(
            """INSERT INTO affected_zones
               (event_id, disaster_type, geom, confidence, area_km2, intensity_metadata, source)
               VALUES (%s::uuid, %s, ST_SetSRID(ST_GeomFromGeoJSON(%s),4326), %s, %s, %s::jsonb, 'demo')""",
            (event_uuid, dtype, geom_str, conf, area, json.dumps(meta)),
        )
        inserted += 1
    return inserted


# ── MAIN ──────────────────────────────────────────────────────────────────

def main(args):

    # ── STEP 1: Create DB ────────────────────────────────────────────
    banner("STEP 1 — Create orbitalmind database")
    try:
        conn0 = connect(args.host, args.port, args.user, args.password, "postgres")
        conn0.autocommit = True
        with conn0.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname='orbitalmind'")
            if cur.fetchone():
                ok("Database 'orbitalmind' already exists")
            else:
                cur.execute("CREATE DATABASE orbitalmind")
                ok("Created database 'orbitalmind'")
        conn0.close()
    except psycopg2.OperationalError as e:
        fail(f"Cannot connect to PostgreSQL: {e}")
        print("\n  Hint: Make sure PostgreSQL is running:")
        print("        net start postgresql-x64-18")
        sys.exit(1)

    # ── STEP 2: Connect to orbitalmind + enable extensions ───────────
    banner("STEP 2 — Enable PostGIS + uuid-ossp")
    try:
        conn = connect(args.host, args.port, args.user, args.password, "orbitalmind")
        conn.autocommit = True
    except psycopg2.OperationalError as e:
        fail(f"Cannot connect to orbitalmind DB: {e}")
        sys.exit(1)

    with conn.cursor() as cur:
        for ext in ("postgis", "postgis_topology", "uuid-ossp", "pg_trgm"):
            try:
                cur.execute(f'CREATE EXTENSION IF NOT EXISTS "{ext}"')
                ok(f"Extension: {ext}")
            except psycopg2.Error as e:
                warn(f"Extension {ext} skipped: {e.pgerror or e}")
                conn.rollback()

    conn.autocommit = False

    # ── STEP 3: Load schema.sql ───────────────────────────────────────
    banner("STEP 3 — Load db/schema.sql (tables + seed data)")
    schema_path = _REPO / "db" / "schema.sql"
    if not schema_path.exists():
        fail(f"Schema not found: {schema_path}")
        sys.exit(1)
    try:
        run_sql_file(conn, schema_path, "db/schema.sql")
    except psycopg2.Error as e:
        warn(f"schema.sql had an error (may already exist): {e.pgerror or str(e)[:120]}")
        conn.rollback()

    # ── STEP 4: Load priority_scoring.sql ────────────────────────────
    banner("STEP 4 — Install calculate_priority_score() function")
    scoring_path = _REPO / "db" / "priority_scoring.sql"
    if not scoring_path.exists():
        fail(f"Not found: {scoring_path}")
        sys.exit(1)
    try:
        run_sql_file(conn, scoring_path, "db/priority_scoring.sql")
    except psycopg2.Error as e:
        warn(f"priority_scoring.sql error: {e.pgerror or str(e)[:120]}")
        conn.rollback()

    # ── STEP 5 + 6: Load demo events + score ─────────────────────────
    banner("STEP 5+6 — Load demo events + score all districts")
    manifest_path = _REPO / "backend" / "demo_data" / "events_manifest.json"
    if not manifest_path.exists():
        fail(f"Manifest not found: {manifest_path}")
        print("  Run: python scripts/generate_mock_data.py")
        sys.exit(1)

    events = json.loads(manifest_path.read_text())["events"]
    print(f"\n  Found {len(events)} events in manifest\n")

    # Check planet_osm_point
    with conn.cursor() as cur:
        cur.execute(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='planet_osm_point')"
        )
        osm_loaded = cur.fetchone()[0]
    if not osm_loaded:
        warn("planet_osm_point missing — infrastructure counts will be 0")
        print("        Fix: osm2pgsql -d orbitalmind -H localhost -U postgres kerala-latest.osm.pbf\n")

    all_pass = True
    for ev in events:
        dtype    = ev["disaster_type"]
        event_id = ev["event_id"]
        name     = ev.get("display_name", event_id)
        date_str = ev.get("date_start")
        print(f"  -- {name} ({dtype})")

        geojson_path = get_geojson_path(ev)
        if not geojson_path:
            warn(f"GeoJSON not found for {event_id}")
            all_pass = False
            continue

        try:
            with conn.cursor() as cur:
                # Find seeded event UUID
                if date_str:
                    cur.execute(
                        "SELECT event_id FROM disaster_events WHERE disaster_type=%s AND date_start=%s LIMIT 1",
                        (dtype, date_str),
                    )
                else:
                    cur.execute(
                        "SELECT event_id FROM disaster_events WHERE disaster_type=%s LIMIT 1",
                        (dtype,),
                    )
                row = cur.fetchone()
                if not row:
                    warn(f"  Event not in disaster_events for type={dtype}")
                    all_pass = False
                    continue
                event_uuid = str(row[0])

                # Clear existing
                cur.execute("DELETE FROM priority_results WHERE event_id=%s::uuid", (event_uuid,))
                cur.execute("DELETE FROM affected_zones WHERE event_id=%s::uuid",   (event_uuid,))

                # Load zones
                n = load_zones(cur, event_uuid, dtype, geojson_path)
                print(f"     Loaded     : {n} zones")

                # Score
                try:
                    cur.execute(
                        "SELECT zone_name, priority_score, priority_rank, hospitals_affected "
                        "FROM calculate_priority_score(%s::uuid, %s) ORDER BY priority_rank LIMIT 1",
                        (event_uuid, dtype),
                    )
                    row = cur.fetchone()
                    if row:
                        zone_name, score, rank, hosp = row
                        score = float(score or 0)
                        print(f"     Top zone   : {zone_name}  score={score:.4f}  hospitals={hosp or 0}")
                        print(f"     OK {name} ({dtype})")
                    else:
                        warn(f"  Scoring returned 0 rows (admin_zones overlap needed)")
                except psycopg2.Error as e:
                    if "planet_osm" in str(e).lower() or "column" in str(e).lower():
                        warn(f"  Scoring skipped (OSM/schema issue): {str(e)[:80]}")
                        conn.rollback()
                    else:
                        raise

            conn.commit()

        except Exception as e:
            conn.rollback()
            fail(f"  {name}: {e}")
            traceback.print_exc()
            all_pass = False

    # ── STEP 7: Validate Kerala ───────────────────────────────────────
    banner("STEP 7 — Validate Kerala 2018 flood")
    try:
        with conn.cursor() as cur:
            # Event
            cur.execute("SELECT event_id FROM disaster_events WHERE disaster_type='flood' LIMIT 1")
            row = cur.fetchone()
            if not row:
                fail("No flood event found"); conn.close(); sys.exit(1)
            event_uuid = str(row[0])
            ok(f"Flood event UUID: {event_uuid[:8]}...")

            # Zones
            cur.execute("SELECT COUNT(*) FROM affected_zones WHERE event_id=%s::uuid", (event_uuid,))
            n_zones = cur.fetchone()[0]
            if n_zones: ok(f"affected_zones: {n_zones} features")
            else:       fail("No zones in affected_zones")

            # Priority results
            cur.execute("SELECT COUNT(*) FROM priority_results WHERE event_id=%s::uuid", (event_uuid,))
            n_res = cur.fetchone()[0]
            if n_res: ok(f"priority_results: {n_res} districts scored")
            else:     warn("priority_results empty (admin_zones overlap needed)")

            # Top zone
            cur.execute("""
                SELECT adm.name, pr.priority_score, pr.hospitals_affected, adm.population
                FROM priority_results pr
                JOIN admin_zones adm ON pr.admin_zone_id = adm.zone_id
                WHERE pr.event_id = %s::uuid
                ORDER BY pr.priority_rank LIMIT 1
            """, (event_uuid,))
            top = cur.fetchone()
            if top:
                zone_name, score, hosp, pop = top
                score = float(score or 0)
                ok(f"Top zone: {zone_name}  score={score:.4f}  hospitals={hosp or 0}  pop={pop or 0:,}")
                if score > 0.6: ok(f"Score > 0.6: PASS ({score:.4f})")
                else:           fail(f"Score > 0.6: FAIL ({score:.4f})")
                if (pop or 0) >= 50000: ok(f"Population >= 50,000: PASS ({pop:,})")
                else:                   warn(f"Population < 50,000: check admin_zones table")
            else:
                warn("No top zone found — admin_zones may be empty")
                print("  Run: python scripts/import_admin_zones.py")

    except psycopg2.Error as e:
        fail(f"Validation error: {e}")

    conn.close()

    banner("BOOTSTRAP COMPLETE")
    if all_pass:
        print("  All steps completed.")
        print("  Run the summary:  python -c \"import psycopg2; ...\"")
        print("  Or view in psql:  psql -U postgres -d orbitalmind -f db/multi_disaster_summary.sql")
    else:
        print("  Some steps had warnings. Check output above.")
    print()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Bootstrap OrbitalMind database end-to-end")
    p.add_argument("--host",     default="localhost")
    p.add_argument("--port",     type=int, default=5432)
    p.add_argument("--user",     default="postgres")
    p.add_argument("--password", default="postgres")
    main(p.parse_args())
