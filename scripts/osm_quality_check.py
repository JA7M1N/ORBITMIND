"""
OrbitalMind — OSM Data Quality Check
======================================
Audits the planet_osm_* tables imported via osm2pgsql and prints a
structured quality report.  Run after importing Kerala OSM data.

Usage
-----
    python scripts/osm_quality_check.py
    python scripts/osm_quality_check.py --password postgres --host localhost

Exit codes
----------
    0  All checks pass
    1  Warnings found (data may be incomplete but usable)
    2  Critical failure (OSM tables missing — import not done)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import psycopg2
import psycopg2.extras

# ── Formatting helpers ────────────────────────────────────────────────────────

def banner(msg: str) -> None:
    width = 66
    print(f"\n{'=' * width}")
    print(f"  {msg}")
    print(f"{'=' * width}")

def row_fmt(label: str, value: str | int, status: str = "", note: str = "") -> str:
    status_col = f"[{status}]" if status else ""
    return f"  {label:<36} {str(value):>8}   {status_col:<8} {note}"

def divider() -> None:
    print("  " + "-" * 62)


# ── DB connection ─────────────────────────────────────────────────────────────

def connect(args: argparse.Namespace) -> psycopg2.extensions.connection:
    return psycopg2.connect(
        host=args.host,
        port=args.port,
        user=args.user,
        password=args.password,
        dbname=args.dbname,
    )


# ── Individual checks ─────────────────────────────────────────────────────────

def check_osm_tables(cur: psycopg2.extensions.cursor) -> bool:
    """Return True if planet_osm_point and planet_osm_line exist."""
    cur.execute(
        """
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_name IN (
              'planet_osm_point', 'planet_osm_line',
              'planet_osm_polygon', 'planet_osm_roads'
          )
        ORDER BY table_name
        """
    )
    found = {r[0] for r in cur.fetchall()}
    return len(found) >= 2


def count_amenity(cur: psycopg2.extensions.cursor, amenity: str, table: str = "planet_osm_point") -> int:
    try:
        cur.execute(f"SELECT COUNT(*) FROM {table} WHERE amenity = %s", (amenity,))
        return cur.fetchone()[0]
    except psycopg2.Error:
        return -1


def count_highways(cur: psycopg2.extensions.cursor) -> int:
    try:
        cur.execute("SELECT COUNT(*) FROM planet_osm_line WHERE highway IS NOT NULL")
        return cur.fetchone()[0]
    except psycopg2.Error:
        return -1


def count_null_geom_point(cur: psycopg2.extensions.cursor) -> int:
    try:
        cur.execute("SELECT COUNT(*) FROM planet_osm_point WHERE way IS NULL")
        return cur.fetchone()[0]
    except psycopg2.Error:
        return -1


def count_null_geom_line(cur: psycopg2.extensions.cursor) -> int:
    try:
        cur.execute("SELECT COUNT(*) FROM planet_osm_line WHERE way IS NULL")
        return cur.fetchone()[0]
    except psycopg2.Error:
        return -1


def count_bridges(cur: psycopg2.extensions.cursor) -> int:
    try:
        cur.execute("SELECT COUNT(*) FROM planet_osm_line WHERE bridge = 'yes'")
        return cur.fetchone()[0]
    except psycopg2.Error:
        return -1


def count_waterways(cur: psycopg2.extensions.cursor) -> int:
    try:
        cur.execute("SELECT COUNT(*) FROM planet_osm_line WHERE waterway IS NOT NULL")
        return cur.fetchone()[0]
    except psycopg2.Error:
        return -1


def count_total_points(cur: psycopg2.extensions.cursor) -> int:
    try:
        cur.execute("SELECT COUNT(*) FROM planet_osm_point")
        return cur.fetchone()[0]
    except psycopg2.Error:
        return -1


def count_admin_boundaries(cur: psycopg2.extensions.cursor) -> int:
    """Count admin_level=6 polygons (district boundaries in India)."""
    try:
        cur.execute(
            "SELECT COUNT(*) FROM planet_osm_polygon WHERE admin_level = '6'"
        )
        return cur.fetchone()[0]
    except psycopg2.Error:
        return -1


def sample_hospital_names(cur: psycopg2.extensions.cursor, limit: int = 5) -> list[str]:
    try:
        cur.execute(
            "SELECT name FROM planet_osm_point WHERE amenity='hospital' AND name IS NOT NULL LIMIT %s",
            (limit,)
        )
        return [r[0] for r in cur.fetchall()]
    except psycopg2.Error:
        return []


# ── Main report ───────────────────────────────────────────────────────────────

def run(args: argparse.Namespace) -> int:
    banner("OrbitalMind - Kerala OSM Data Quality Report")

    # Connect
    try:
        conn = connect(args)
        cur  = conn.cursor()
        print(f"\n  Connected: {args.host}:{args.port}/{args.dbname}")
    except psycopg2.OperationalError as e:
        print(f"\n  [CRITICAL]  Cannot connect to PostgreSQL: {e}")
        print("  Start PostgreSQL: net start postgresql-x64-18")
        return 2

    # Check OSM tables exist
    print()
    if not check_osm_tables(cur):
        print("  [CRITICAL]  OSM tables not found!")
        print("  Run: osm2pgsql -d orbitalmind -H localhost -U postgres --create --slim kerala-latest.osm.pbf")
        print("  Download: https://download.geofabrik.de/asia/india/kerala-latest.osm.pbf")
        cur.close(); conn.close()
        return 2

    print("  [  OK  ]  planet_osm_* tables found\n")

    # ── Infrastructure counts ──────────────────────────────────────────────
    warnings = 0

    hospitals   = count_amenity(cur, "hospital")
    clinics     = count_amenity(cur, "clinic")
    schools     = count_amenity(cur, "school")
    colleges    = count_amenity(cur, "college")
    highways    = count_highways(cur)
    bridges     = count_bridges(cur)
    waterways   = count_waterways(cur)
    null_pts    = count_null_geom_point(cur)
    null_lines  = count_null_geom_line(cur)
    total_pts   = count_total_points(cur)
    admin_bound = count_admin_boundaries(cur)

    # ── Print table ────────────────────────────────────────────────────────
    print(f"  {'Metric':<36} {'Count':>8}   {'Status':<8} {'Notes'}")
    divider()

    # Hospitals
    hosp_status = "OK" if hospitals >= 50 else ("WARN" if hospitals >= 10 else "LOW")
    hosp_note   = "" if hospitals >= 50 else "may be incomplete"
    print(row_fmt("Hospitals (amenity=hospital)", hospitals, hosp_status, hosp_note))
    if hospitals >= 0: print(row_fmt("  + Clinics (amenity=clinic)", clinics, "", ""))

    # Schools
    sch_status = "OK" if schools >= 100 else "WARN"
    print(row_fmt("Schools (amenity=school)", schools, sch_status, ""))
    if colleges >= 0: print(row_fmt("  + Colleges (amenity=college)", colleges, "", ""))

    divider()

    # Roads & bridges
    hw_status = "OK" if highways >= 5000 else "WARN"
    print(row_fmt("Highway segments", highways, hw_status, ""))
    print(row_fmt("Bridges (bridge=yes)", bridges, "OK" if bridges >= 0 else "ERR", ""))
    print(row_fmt("Waterways", waterways, "OK", ""))

    divider()

    # Geometry quality
    null_status = "OK" if null_pts == 0 else "WARN"
    print(row_fmt("Points with NULL geometry", null_pts, null_status, ""))
    print(row_fmt("Lines with NULL geometry", null_lines, "OK" if null_lines == 0 else "WARN", ""))
    print(row_fmt("Total point features", total_pts, "OK", ""))
    print(row_fmt("Admin boundaries (level=6)", admin_bound, "OK" if admin_bound >= 14 else "WARN",
                  "expect 14 for Kerala"))

    divider()

    # ── Warnings block ─────────────────────────────────────────────────────
    print()
    if hospitals < 50:
        warnings += 1
        print("  [WARNING]  Hospitals < 50 — rural Kerala coverage may be incomplete.")
        print("             OSM hospital data relies on volunteer mapping; rural taluks")
        print("             are often under-mapped compared to district capitals.")
        print()
        print("  [ACTION]   Supplement from authoritative sources:")
        print("             - HMIS (Health Management Info System): data.gov.in/catalog/health-facilities")
        print("             - NHM Kerala: https://nrhm.kerala.gov.in")
        print("             - Geo-code and import as additional planet_osm_point rows,")
        print("               OR use scripts/generate_mock_priority_fallback.py for demo.")
        print()

    if schools < 100:
        warnings += 1
        print("  [WARNING]  Schools < 100 — coverage may be partial for rural taluks.")
        print("             DISE/UDISE database has full coverage: udiseplus.gov.in")
        print()

    if null_pts > 0:
        warnings += 1
        print(f"  [WARNING]  {null_pts} point features have NULL geometry — these will")
        print("             be ignored by ST_Intersects queries. Usually safe to ignore.")
        print()

    # ── Sample hospital names ──────────────────────────────────────────────
    names = sample_hospital_names(cur)
    if names:
        print("  Sample hospital names in OSM:")
        for n in names:
            print(f"    - {n}")
        print()

    # ── Summary ───────────────────────────────────────────────────────────
    banner("Quality Report Summary")
    print(f"\n  Hospitals found : {hospitals:,}")
    print(f"  Schools found   : {schools:,}")
    print(f"  Highway segments: {highways:,}")
    print(f"  NULL geometries : {null_pts + null_lines}")
    print(f"  Warnings        : {warnings}")
    print()

    if warnings == 0:
        print("  RESULT: OSM data quality is GOOD for demo purposes.")
        print("          Infrastructure overlay will use live OSM counts.")
    else:
        print(f"  RESULT: {warnings} warning(s) found.")
        print("          For demo: run scripts/generate_mock_priority_fallback.py")
        print("          to load pre-computed realistic hospital/school counts.")
        print("          Live ST_Intersects queries will still work but counts may be lower.")

    print()
    cur.close()
    conn.close()
    return 1 if warnings > 0 else 0


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    p = argparse.ArgumentParser(description="OrbitalMind Kerala OSM Quality Check")
    p.add_argument("--host",     default="localhost")
    p.add_argument("--port",     type=int, default=5432)
    p.add_argument("--user",     default="postgres")
    p.add_argument("--password", default="postgres")
    p.add_argument("--dbname",   default="orbitalmind")
    sys.exit(run(p.parse_args()))
