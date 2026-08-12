"""
OrbitalMind — Schema Loader (PostGIS-aware fallback)
=====================================================
Loads the correct schema based on what's available:
  - PostGIS installed → full schema with geometry columns (db/schema.sql)
  - PostGIS missing   → fallback schema with TEXT geom (db/schema_no_postgis.sql)

Also seeds the 5 disaster events and loads demo GeoJSON data.

Usage
-----
    python scripts/setup_schema.py --password postgres
    python scripts/setup_schema.py --password postgres --force-rebuild
"""

from __future__ import annotations
import argparse, json, sys
from pathlib import Path
import psycopg2, psycopg2.extras
psycopg2.extras.register_uuid()

_REPO = Path(__file__).resolve().parents[1]

FALLBACK_SCHEMA = """
-- OrbitalMind fallback schema (no PostGIS dependency)
-- Geometry columns stored as TEXT (GeoJSON strings) until PostGIS is installed.

CREATE TABLE IF NOT EXISTS disaster_events (
    event_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    disaster_type   VARCHAR(30)  NOT NULL,
    display_name    VARCHAR(200) NOT NULL,
    region          VARCHAR(200),
    state           VARCHAR(100),
    date_start      DATE,
    date_end        DATE,
    status          VARCHAR(20)  DEFAULT 'live',
    data_source     VARCHAR(200),
    thumbnail_color VARCHAR(10),
    description     TEXT,
    bbox_text       TEXT,          -- WKT / GeoJSON bbox string (PostGIS-free)
    created_at      TIMESTAMPTZ  DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS affected_zones (
    zone_id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id            UUID         REFERENCES disaster_events(event_id) ON DELETE CASCADE,
    disaster_type       VARCHAR(30),
    geom_text           TEXT,          -- GeoJSON geometry string
    confidence          FLOAT        CHECK (confidence BETWEEN 0 AND 1),
    area_km2            FLOAT,
    intensity_metadata  JSONB        DEFAULT '{}',
    source              VARCHAR(50)  DEFAULT 'demo',
    created_at          TIMESTAMPTZ  DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS admin_zones (
    zone_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        VARCHAR(200),
    district    VARCHAR(200),
    state       VARCHAR(100),
    population  BIGINT,
    area_km2    FLOAT,
    geom_text   TEXT
);

CREATE TABLE IF NOT EXISTS priority_results (
    result_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id            UUID         REFERENCES disaster_events(event_id) ON DELETE CASCADE,
    admin_zone_id       UUID         REFERENCES admin_zones(zone_id),
    disaster_type       VARCHAR(30),
    zone_name           VARCHAR(200),
    priority_rank       INTEGER,
    priority_score      FLOAT,
    population_score    FLOAT,
    infra_score         FLOAT,
    access_score        FLOAT,
    intensity_score     FLOAT,
    hospitals_affected  INTEGER DEFAULT 0,
    schools_affected    INTEGER DEFAULT 0,
    bridges_affected    INTEGER DEFAULT 0,
    scoring_weights     JSONB,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pr_event    ON priority_results(event_id);
CREATE INDEX IF NOT EXISTS idx_pr_rank     ON priority_results(event_id, priority_rank);
CREATE INDEX IF NOT EXISTS idx_az_event    ON affected_zones(event_id);
CREATE INDEX IF NOT EXISTS idx_de_type     ON disaster_events(disaster_type);
"""

SEED_EVENTS = [
    {
        "disaster_type": "flood",
        "display_name": "Kerala Floods 2018",
        "region": "Kerala", "state": "Kerala",
        "date_start": "2018-08-01", "date_end": "2018-08-31",
        "status": "live", "data_source": "Sentinel-1 SAR + Attention U-Net",
        "thumbnail_color": "#1e40af",
        "description": "Catastrophic flooding following extreme monsoon rainfall across 14 Kerala districts.",
        "bbox_text": "POLYGON((76.0 9.5, 77.5 9.5, 77.5 11.0, 76.0 11.0, 76.0 9.5))",
    },
    {
        "disaster_type": "wildfire",
        "display_name": "Uttarakhand Forest Fires 2024",
        "region": "Garhwal & Kumaon", "state": "Uttarakhand",
        "date_start": "2024-04-15", "date_end": "2024-05-10",
        "status": "demo", "data_source": "Sentinel-2 SWIR + NBR Ratio",
        "thumbnail_color": "#dc2626",
        "description": "Widespread forest fires across Garhwal and Kumaon divisions.",
        "bbox_text": "POLYGON((78.5 29.5, 80.5 29.5, 80.5 31.5, 78.5 31.5, 78.5 29.5))",
    },
    {
        "disaster_type": "landslide",
        "display_name": "Himachal Pradesh Landslides 2023",
        "region": "Shimla & Kullu", "state": "Himachal Pradesh",
        "date_start": "2023-07-10", "date_end": "2023-08-15",
        "status": "demo", "data_source": "Sentinel-1 SAR + SRTM DEM",
        "thumbnail_color": "#b45309",
        "description": "Series of landslides triggered by above-normal monsoon rainfall.",
        "bbox_text": "POLYGON((77.0 31.0, 78.5 31.0, 78.5 32.5, 77.0 32.5, 77.0 31.0))",
    },
    {
        "disaster_type": "cyclone",
        "display_name": "Cyclone Michaung 2023",
        "region": "Coastal Odisha", "state": "Odisha",
        "date_start": "2023-12-04", "date_end": "2023-12-06",
        "status": "demo", "data_source": "INSAT-3D + IMD Track Data",
        "thumbnail_color": "#7c3aed",
        "description": "Severe cyclone making landfall near Bapatla with wind speeds 90-100 kmph.",
        "bbox_text": "POLYGON((82.0 15.0, 86.0 15.0, 86.0 20.5, 82.0 20.5, 82.0 15.0))",
    },
    {
        "disaster_type": "earthquake",
        "display_name": "Gujarat Earthquake 2024",
        "region": "Kutch", "state": "Gujarat",
        "date_start": "2024-03-15", "date_end": "2024-03-15",
        "status": "demo", "data_source": "Sentinel-1 InSAR + USGS ShakeMap",
        "thumbnail_color": "#d97706",
        "description": "M5.8 earthquake in Kutch district near Bhuj epicentre.",
        "bbox_text": "POLYGON((69.0 22.5, 71.5 22.5, 71.5 24.5, 69.0 24.5, 69.0 22.5))",
    },
]

# Kerala admin zones (14 districts, 2011 census)
KERALA_ADMIN_ZONES = [
    {"name": "Ernakulam",   "district": "Ernakulam",   "state": "Kerala", "population": 3282388, "area_km2": 2817},
    {"name": "Alappuzha",   "district": "Alappuzha",   "state": "Kerala", "population": 2127789, "area_km2": 1414},
    {"name": "Thrissur",    "district": "Thrissur",    "state": "Kerala", "population": 3121200, "area_km2": 3032},
    {"name": "Palakkad",    "district": "Palakkad",    "state": "Kerala", "population": 2809934, "area_km2": 4480},
    {"name": "Malappuram",  "district": "Malappuram",  "state": "Kerala", "population": 4112920, "area_km2": 3550},
    {"name": "Kozhikode",   "district": "Kozhikode",   "state": "Kerala", "population": 3086293, "area_km2": 2345},
    {"name": "Idukki",      "district": "Idukki",      "state": "Kerala", "population": 1108974, "area_km2": 4358},
    {"name": "Kottayam",    "district": "Kottayam",    "state": "Kerala", "population": 1974551, "area_km2": 2208},
    {"name": "Kannur",      "district": "Kannur",      "state": "Kerala", "population": 2523003, "area_km2": 2966},
    {"name": "Kollam",      "district": "Kollam",      "state": "Kerala", "population": 2635375, "area_km2": 2491},
    {"name": "Thiruvananthapuram", "district": "Thiruvananthapuram", "state": "Kerala", "population": 3301427, "area_km2": 2192},
    {"name": "Wayanad",     "district": "Wayanad",     "state": "Kerala", "population": 817420,  "area_km2": 2132},
    {"name": "Pathanamthitta","district":"Pathanamthitta","state":"Kerala","population": 1197412, "area_km2": 2637},
    {"name": "Kasaragod",   "district": "Kasaragod",   "state": "Kerala", "population": 1307375, "area_km2": 1992},
]

# Pre-computed priority scores for Kerala flood (from sample_api_response.json)
KERALA_PRIORITY = [
    {"zone": "Ernakulam",   "rank": 1, "score": 0.8714, "hosp": 12, "sch": 28, "br": 4, "access": 0.42},
    {"zone": "Alappuzha",   "rank": 2, "score": 0.8203, "hosp":  8, "sch": 19, "br": 6, "access": 0.31},
    {"zone": "Thrissur",    "rank": 3, "score": 0.7138, "hosp":  6, "sch": 22, "br": 3, "access": 0.58},
    {"zone": "Palakkad",    "rank": 4, "score": 0.6347, "hosp":  4, "sch": 15, "br": 2, "access": 0.71},
    {"zone": "Malappuram",  "rank": 5, "score": 0.5912, "hosp":  5, "sch": 18, "br": 2, "access": 0.77},
    {"zone": "Kozhikode",   "rank": 6, "score": 0.5441, "hosp":  4, "sch": 13, "br": 2, "access": 0.79},
    {"zone": "Idukki",      "rank": 7, "score": 0.5183, "hosp":  3, "sch":  9, "br": 4, "access": 0.52},
    {"zone": "Kottayam",    "rank": 8, "score": 0.4876, "hosp":  3, "sch": 11, "br": 2, "access": 0.65},
]

_EXCLUDE = {"confidence", "area_km2", "disaster_type"}

def banner(msg): print(f"\n{'='*60}\n  {msg}\n{'='*60}")
def ok(msg):     print(f"  [  OK  ]  {msg}")
def warn(msg):   print(f"  [ WARN ]  {msg}")
def fail(msg):   print(f"  [ FAIL ]  {msg}")

def connect(args, db="postgres"):
    return psycopg2.connect(host=args.host, port=args.port,
                            user=args.user, password=args.password, dbname=db)

def main(args):
    # ── STEP 1: connect + check PostGIS ───────────────────────────────
    banner("STEP 1 — Connect + check PostGIS availability")
    try:
        conn = connect(args, "orbitalmind")
    except psycopg2.OperationalError:
        try:
            c0 = connect(args, "postgres")
            c0.autocommit = True
            with c0.cursor() as cur:
                cur.execute("CREATE DATABASE orbitalmind")
            c0.close()
            ok("Created database 'orbitalmind'")
            conn = connect(args, "orbitalmind")
        except psycopg2.Error as e:
            fail(f"Cannot connect: {e}")
            print("  Make sure PostgreSQL is running: net start postgresql-x64-18")
            sys.exit(1)

    conn.autocommit = True
    with conn.cursor() as cur:
        # Enable uuid-ossp (always available)
        try:
            cur.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
            ok("Extension: uuid-ossp")
        except psycopg2.Error:
            conn.rollback()

        # Try PostGIS
        try:
            cur.execute('CREATE EXTENSION IF NOT EXISTS postgis')
            cur.execute('SELECT PostGIS_Version()')
            ver = cur.fetchone()[0]
            postgis_ok = True
            ok(f"Extension: postgis {ver}")
        except psycopg2.Error:
            postgis_ok = False
            warn("PostGIS NOT available — using text-geometry fallback schema")
            print("        Install PostGIS via StackBuilder then re-run this script.")

    conn.autocommit = False

    # ── STEP 2: Load schema ───────────────────────────────────────────
    banner("STEP 2 — Create tables")
    if postgis_ok:
        schema_path = _REPO / "db" / "schema.sql"
        sql = schema_path.read_text(encoding="utf-8")
        lines = [l for l in sql.splitlines() if not l.strip().startswith("\\")]
        sql_clean = "\n".join(lines)
    else:
        sql_clean = FALLBACK_SCHEMA

    with conn.cursor() as cur:
        try:
            cur.execute(sql_clean)
            conn.commit()
            ok("Tables created" + (" (full PostGIS schema)" if postgis_ok else " (fallback text-geom schema)"))
        except psycopg2.Error as e:
            conn.rollback()
            # If tables exist, that's fine
            if "already exists" in str(e):
                ok("Tables already exist — skipping")
            else:
                warn(f"Schema error: {str(e)[:200]}")
                # Try table-by-table with the fallback
                with conn.cursor() as cur2:
                    try:
                        cur2.execute(FALLBACK_SCHEMA)
                        conn.commit()
                        ok("Fallback schema applied")
                    except psycopg2.Error as e2:
                        conn.rollback()
                        warn(f"Fallback schema also had errors: {str(e2)[:120]}")

    # ── STEP 3: Verify disaster_events table exists ───────────────────
    banner("STEP 3 — Verify tables")
    with conn.cursor() as cur:
        for table in ("disaster_events", "affected_zones", "admin_zones", "priority_results"):
            cur.execute(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name=%s)",
                (table,)
            )
            exists = cur.fetchone()[0]
            if exists: ok(f"Table: {table}")
            else:      fail(f"Table missing: {table}")

    # ── STEP 4: Seed events ───────────────────────────────────────────
    banner("STEP 4 — Seed disaster_events (5 demo events)")
    with conn.cursor() as cur:
        for ev in SEED_EVENTS:
            if postgis_ok:
                cur.execute("""
                    INSERT INTO disaster_events
                        (disaster_type, display_name, region, state, date_start, date_end,
                         status, data_source, thumbnail_color, description, bbox)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                        ST_GeomFromText(%s, 4326))
                    ON CONFLICT ON CONSTRAINT uq_disaster_events_type_date_region DO NOTHING
                """, (ev["disaster_type"], ev["display_name"], ev["region"], ev["state"],
                      ev["date_start"], ev["date_end"], ev["status"], ev["data_source"],
                      ev["thumbnail_color"], ev["description"], ev["bbox_text"]))
            else:
                cur.execute("""
                    INSERT INTO disaster_events
                        (disaster_type, display_name, region, state, date_start, date_end,
                         status, data_source, thumbnail_color, description, bbox_text)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT DO NOTHING
                """, (ev["disaster_type"], ev["display_name"], ev["region"], ev["state"],
                      ev["date_start"], ev["date_end"], ev["status"], ev["data_source"],
                      ev["thumbnail_color"], ev["description"], ev["bbox_text"]))
            ok(f"Seeded: {ev['display_name']}")
        conn.commit()

    # ── STEP 5: Seed admin_zones (Kerala districts) ───────────────────
    banner("STEP 5 — Seed admin_zones (14 Kerala districts)")
    with conn.cursor() as cur:
        # Check if already seeded
        cur.execute("SELECT COUNT(*) FROM admin_zones WHERE state='Kerala'")
        n = cur.fetchone()[0]
        if n >= 14:
            ok(f"Kerala districts already seeded ({n} rows) — skipping")
        else:
            for z in KERALA_ADMIN_ZONES:
                cur.execute("""
                    INSERT INTO admin_zones (name, district, state, population, area_km2)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                """, (z["name"], z["district"], z["state"], z["population"], z["area_km2"]))
            conn.commit()
            ok(f"Seeded {len(KERALA_ADMIN_ZONES)} Kerala districts")

    # ── STEP 6: Load affected_zones from GeoJSON ─────────────────────
    banner("STEP 6 — Load affected_zones from GeoJSON files")
    manifest_path = _REPO / "backend" / "demo_data" / "events_manifest.json"
    events = json.loads(manifest_path.read_text())["events"]

    for ev in events:
        dtype    = ev["disaster_type"]
        event_id_slug = ev["event_id"]
        name     = ev.get("display_name", event_id_slug)
        date_str = ev.get("date_start")

        # Find GeoJSON
        demo_data = _REPO / "backend" / "demo_data"
        geojson_path = None
        for n in ("flood_mask.geojson", "affected_zones.geojson"):
            p = demo_data / dtype / event_id_slug / n
            if p.exists():
                geojson_path = p
                break

        if not geojson_path:
            warn(f"GeoJSON not found for {event_id_slug}")
            continue

        with conn.cursor() as cur:
            # Get event UUID
            if date_str:
                cur.execute("SELECT event_id FROM disaster_events WHERE disaster_type=%s AND date_start=%s LIMIT 1",
                            (dtype, date_str))
            else:
                cur.execute("SELECT event_id FROM disaster_events WHERE disaster_type=%s LIMIT 1", (dtype,))
            row = cur.fetchone()
            if not row:
                warn(f"Event not found for {dtype}")
                continue
            event_uuid = str(row[0])

            # Clear and reload
            cur.execute("DELETE FROM affected_zones WHERE event_id=%s::uuid", (event_uuid,))

            data     = json.loads(geojson_path.read_text())
            features = [f for f in data.get("features", []) if f.get("geometry")]
            for feat in features:
                props    = feat.get("properties") or {}
                geom_str = json.dumps(feat["geometry"])
                conf     = max(0.0, min(1.0, float(props.get("confidence", 0.5))))
                area     = props.get("area_km2")
                area     = float(area) if area is not None else None
                meta     = {k: v for k, v in props.items() if k not in _EXCLUDE}
                if postgis_ok:
                    cur.execute(
                        "INSERT INTO affected_zones (event_id,disaster_type,geom,confidence,area_km2,intensity_metadata,source) "
                        "VALUES (%s::uuid,%s,ST_SetSRID(ST_GeomFromGeoJSON(%s),4326),%s,%s,%s::jsonb,'demo')",
                        (event_uuid, dtype, geom_str, conf, area, json.dumps(meta))
                    )
                else:
                    cur.execute(
                        "INSERT INTO affected_zones (event_id,disaster_type,geom_text,confidence,area_km2,intensity_metadata,source) "
                        "VALUES (%s::uuid,%s,%s,%s,%s,%s::jsonb,'demo')",
                        (event_uuid, dtype, geom_str, conf, area, json.dumps(meta))
                    )
            conn.commit()
            ok(f"{name}: {len(features)} zones loaded")

    # ── STEP 7: Insert pre-computed priority results for Kerala ───────
    banner("STEP 7 — Insert Kerala priority results (pre-computed)")
    with conn.cursor() as cur:
        # Get flood event UUID
        cur.execute("SELECT event_id FROM disaster_events WHERE disaster_type='flood' LIMIT 1")
        row = cur.fetchone()
        if not row:
            fail("Cannot find flood event")
        else:
            event_uuid = str(row[0])
            cur.execute("DELETE FROM priority_results WHERE event_id=%s::uuid", (event_uuid,))

            weights = {"population": 0.40, "infra": 0.30, "access": 0.20, "intensity": 0.10}
            for p in KERALA_PRIORITY:
                # Find admin_zone_id
                cur.execute("SELECT zone_id, population FROM admin_zones WHERE name=%s AND state='Kerala' LIMIT 1",
                            (p["zone"],))
                az = cur.fetchone()
                if not az:
                    warn(f"admin_zone not found: {p['zone']}")
                    continue
                az_id, pop = az
                # Compute component scores
                max_pop  = 4112920  # Malappuram
                max_inf  = 12*3 + 28*2 + 4   # Ernakulam
                pop_score   = pop / max_pop if pop else 0
                inf_raw     = p["hosp"]*3 + p["sch"]*2 + p["br"]
                infra_score = inf_raw / max_inf
                access      = p["access"]     # roads_intact_pct
                intensity   = p["score"]      # proxy: confidence
                cur.execute("""
                    INSERT INTO priority_results
                        (event_id, admin_zone_id, disaster_type, zone_name,
                         priority_rank, priority_score,
                         population_score, infra_score, access_score, intensity_score,
                         hospitals_affected, schools_affected, bridges_affected,
                         scoring_weights)
                    VALUES (%s::uuid,%s::uuid,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                """, (
                    event_uuid, str(az_id), "flood", p["zone"],
                    p["rank"], p["score"],
                    round(pop_score,4), round(infra_score,4), round(access,4), round(intensity,4),
                    p["hosp"], p["sch"], p["br"],
                    json.dumps(weights)
                ))
            conn.commit()
            ok(f"Inserted {len(KERALA_PRIORITY)} pre-computed priority results for Kerala flood")

    # ── STEP 8: Validate ──────────────────────────────────────────────
    banner("STEP 8 — Validate Kerala 2018")
    fails = 0
    with conn.cursor() as cur:
        cur.execute("SELECT event_id FROM disaster_events WHERE disaster_type='flood' LIMIT 1")
        row = cur.fetchone()
        if not row:
            fail("No flood event"); fails += 1
        else:
            euuid = str(row[0])
            cur.execute("SELECT COUNT(*) FROM affected_zones WHERE event_id=%s::uuid", (euuid,))
            n_az = cur.fetchone()[0]
            if n_az: ok(f"affected_zones: {n_az} features")
            else: fail("No affected_zones"); fails += 1

            cur.execute("SELECT COUNT(*) FROM priority_results WHERE event_id=%s::uuid", (euuid,))
            n_pr = cur.fetchone()[0]
            if n_pr: ok(f"priority_results: {n_pr} districts")
            else: fail("No priority_results"); fails += 1

            cur.execute("""
                SELECT pr.zone_name, pr.priority_score, pr.hospitals_affected, adm.population
                FROM priority_results pr
                JOIN admin_zones adm ON pr.admin_zone_id=adm.zone_id
                WHERE pr.event_id=%s::uuid ORDER BY pr.priority_rank LIMIT 1
            """, (euuid,))
            top = cur.fetchone()
            if top:
                zn, sc, hosp, pop = top
                sc = float(sc)
                ok(f"Top zone: {zn}  score={sc:.4f}  hospitals={hosp}  population={pop:,}")
                if sc > 0.6: ok(f"Score > 0.6: PASS ({sc:.4f})")
                else: fail(f"Score > 0.6: FAIL ({sc:.4f})"); fails+=1
                if (pop or 0) >= 50000: ok(f"Population >= 50,000: PASS ({pop:,})")
                else: warn(f"Population < 50,000 ({pop})")
                if (hosp or 0) >= 1: ok(f"Hospitals >= 1: PASS ({hosp})")
                else: warn("Hospitals = 0 (OSM data needed for live counts)")
            else:
                fail("No top zone found"); fails += 1

    banner("DONE")
    if fails == 0:
        print("  ALL CHECKS PASS")
        if not postgis_ok:
            print()
            print("  NOTE: PostGIS NOT installed — geometry features disabled.")
            print("  To enable full spatial queries:")
            print("  1. Open StackBuilder from the Windows Start Menu")
            print("  2. Select PostgreSQL 18 > Spatial Extensions > PostGIS")
            print("  3. Install, then re-run: python scripts/setup_schema.py")
    else:
        print(f"  {fails} check(s) FAILED — see above")
    print()
    conn.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--host",     default="localhost")
    p.add_argument("--port",     type=int, default=5432)
    p.add_argument("--user",     default="postgres")
    p.add_argument("--password", default="postgres")
    main(p.parse_args())
