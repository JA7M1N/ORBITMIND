"""
OrbitalMind — Kerala 2018 Demo Validation
==========================================
Validates the primary demo event (flood/Kerala 2018) in the PostGIS database.

Checks
------
1. Event exists in disaster_events
2. Affected zones exist in affected_zones
3. Priority results exist in priority_results
4. Top zone has priority_score > 0.6
5. Top zone has population > 50,000
6. Top zone has hospitals_affected >= 1  (WARN if 0 — needs OSM)

Usage
-----
    python scripts/validate_kerala_demo.py
    python scripts/validate_kerala_demo.py --db "postgresql://user:pass@host/db"

Output
------
    PASS or FAIL with fix hints for each check.
    Returns exit code 0 if all hard checks pass, 1 otherwise.
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

# Force UTF-8 on Windows (CP1252 terminal can't print box-drawing chars)
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import psycopg2
import psycopg2.extras
psycopg2.extras.register_uuid()

_DEFAULT_DSN = "postgresql://postgres:postgres@localhost:5432/orbitalmind"

# ── Thresholds ─────────────────────────────────────────────────────────────
MIN_PRIORITY_SCORE  = 0.60
MIN_POPULATION      = 50_000
MIN_HOSPITALS       = 1      # WARN (not FAIL) if 0 — depends on OSM


def run(dsn: str) -> int:
    """Run all validation checks. Returns 0 on pass, 1 on failure."""

    print()
    print("=" * 68)
    print("  OrbitalMind — Kerala 2018 Flood Demo Validation")
    print("=" * 68 + "\n")

    # ── Connect ───────────────────────────────────────────────────────
    try:
        conn = psycopg2.connect(dsn)
        cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    except psycopg2.OperationalError as e:
        _print_fail("Database connection", str(e), "Check PostgreSQL is running: net start postgresql-x64-18")
        return 1

    failures = 0
    warnings = 0

    # ── CHECK 1: Event exists ─────────────────────────────────────────
    cur.execute(
        "SELECT event_id, display_name, date_start, status "
        "FROM disaster_events WHERE disaster_type = 'flood' LIMIT 1"
    )
    event_row = cur.fetchone()

    if not event_row:
        _print_fail(
            "disaster_events.flood",
            "No flood event found in disaster_events table.",
            "Run: psql -U postgres -d orbitalmind -f db/schema.sql",
        )
        cur.close(); conn.close(); return 1

    event_uuid = str(event_row["event_id"])
    _print_pass(
        "Event in disaster_events",
        f"{event_row['display_name']} | UUID: {event_uuid[:8]}…"
    )

    # ── CHECK 2: Affected zones exist ─────────────────────────────────
    cur.execute(
        "SELECT COUNT(*) AS n FROM affected_zones WHERE event_id = %s::uuid",
        (event_uuid,),
    )
    n_zones = cur.fetchone()["n"]

    if n_zones == 0:
        _print_fail(
            "affected_zones",
            "No zones found for this event.",
            "Run: python scripts/load_all_demo_events.py",
        )
        failures += 1
    else:
        _print_pass("Affected zones loaded", f"{n_zones} zone features")

    # ── CHECK 3: Priority results exist ───────────────────────────────
    cur.execute(
        "SELECT COUNT(*) AS n FROM priority_results WHERE event_id = %s::uuid",
        (event_uuid,),
    )
    n_results = cur.fetchone()["n"]

    if n_results == 0:
        _print_fail(
            "priority_results",
            "No priority results found.",
            "Run: python scripts/load_all_demo_events.py  (or psql -f db/priority_scoring.sql first)",
        )
        failures += 1
    else:
        _print_pass("Priority results present", f"{n_results} district scores")

    if failures > 0:
        print(f"\n  ❌  {failures} critical failures — fix above before continuing.\n")
        cur.close(); conn.close(); return 1

    # ── Fetch top 5 priority zones ─────────────────────────────────────
    cur.execute(
        """
        SELECT
            pr.priority_rank,
            adm.name                        AS zone_name,
            ROUND(pr.priority_score::NUMERIC, 4) AS priority_score,
            pr.hospitals_affected,
            pr.schools_affected,
            pr.bridges_affected,
            ROUND(pr.access_score::NUMERIC, 4)    AS roads_disrupted,
            adm.population
        FROM priority_results pr
        JOIN admin_zones adm ON pr.admin_zone_id = adm.zone_id
        WHERE pr.event_id = %s::uuid
        ORDER BY pr.priority_rank
        LIMIT 5
        """,
        (event_uuid,),
    )
    zones = cur.fetchall()

    if not zones:
        _print_fail(
            "Priority zone query",
            "No rows returned (admin_zones may not be loaded).",
            "Run: python scripts/import_admin_zones.py",
        )
        cur.close(); conn.close(); return 1

    # ── Print top 5 table ─────────────────────────────────────────────
    print("\n  Top 5 Priority Zones — Kerala Flood 2018\n")
    print(f"  {'Rank':<5} {'District':<20} {'Score':>6} {'Hosp':>5} {'Sch':>5} {'Pop':>12}")
    print("  " + "-" * 58)
    for z in zones:
        pop_str = f"{z['population']:,}" if z['population'] else "N/A"
        print(
            f"  #{z['priority_rank']:<4} {z['zone_name']:<20} "
            f"{float(z['priority_score']):>6.4f} "
            f"{z['hospitals_affected']:>5} "
            f"{z['schools_affected']:>5} "
            f"{pop_str:>12}"
        )
    print()

    # ── Top zone ─────────────────────────────────────────────────────
    top = zones[0]

    # CHECK 4: Priority score > 0.6
    score = float(top["priority_score"])
    if score > MIN_PRIORITY_SCORE:
        _print_pass(
            f"Top zone score > {MIN_PRIORITY_SCORE}",
            f"{top['zone_name']} → {score:.4f}"
        )
    else:
        _print_fail(
            f"Top zone score > {MIN_PRIORITY_SCORE}",
            f"Got {score:.4f} for {top['zone_name']}",
            "Check scoring weights in db/priority_scoring.sql or re-run load_all_demo_events.py",
        )
        failures += 1

    # CHECK 5: Population > 50,000
    pop = int(top["population"] or 0)
    if pop >= MIN_POPULATION:
        _print_pass(
            f"Top zone population ≥ {MIN_POPULATION:,}",
            f"{top['zone_name']} → {pop:,}"
        )
    else:
        _print_fail(
            f"Top zone population ≥ {MIN_POPULATION:,}",
            f"Got {pop:,} for {top['zone_name']}",
            "Check admin_zones table: SELECT name, population FROM admin_zones WHERE state='Kerala';",
        )
        failures += 1

    # CHECK 6: Hospitals (WARN only — needs OSM)
    hosp = int(top["hospitals_affected"] or 0)
    if hosp >= MIN_HOSPITALS:
        _print_pass(
            f"Top zone hospitals ≥ {MIN_HOSPITALS}",
            f"{top['zone_name']} → {hosp} hospitals in flood zone"
        )
    else:
        _print_warn(
            f"Top zone hospitals < {MIN_HOSPITALS}",
            f"Got {hosp} hospitals for {top['zone_name']}",
            "Import OSM data: osm2pgsql -d orbitalmind -H localhost -U postgres kerala-latest.osm.pbf",
        )
        warnings += 1

    # ── Also verify scoring weights JSONB stored ──────────────────────
    cur.execute(
        "SELECT scoring_weights FROM priority_results "
        "WHERE event_id = %s::uuid LIMIT 1",
        (event_uuid,),
    )
    row = cur.fetchone()
    if row and row["scoring_weights"]:
        import json
        weights = row["scoring_weights"]
        if isinstance(weights, str):
            weights = json.loads(weights)
        w_sum = sum(weights.values())
        if abs(w_sum - 1.0) < 0.01:
            _print_pass("Scoring weights JSONB", f"Stored correctly → {weights}")
        else:
            _print_warn("Scoring weights sum", f"Sum = {w_sum:.2f} (expected 1.0)", "Check priority_scoring.sql CASE block")
            warnings += 1
    else:
        _print_warn("Scoring weights JSONB", "Not stored (NULL)", "Re-run load_all_demo_events.py")
        warnings += 1

    cur.close()
    conn.close()

    # ── Summary ───────────────────────────────────────────────────────
    print()
    print("=" * 68)
    if failures == 0:
        print(f"  ✅  PASS  —  {n_results} districts scored  |  {warnings} warning(s)")
        print("  Kerala 2018 demo is ready for judges.")
    else:
        print(f"  ❌  FAIL  —  {failures} hard failure(s)  |  {warnings} warning(s)")
        print("  Fix the RED items above and re-run this script.")
    print("=" * 68 + "\n")

    return 0 if failures == 0 else 1


# ── Pretty-print helpers ───────────────────────────────────────────────────

def _print_pass(check: str, detail: str = "") -> None:
    detail_str = f"  ({detail})" if detail else ""
    print(f"  [  PASS  ]  {check:<42}{detail_str}")

def _print_warn(check: str, detail: str, fix: str) -> None:
    print(f"  [  WARN  ]  {check}")
    if detail: print(f"              Got  : {detail}")
    print(f"              Fix  : {fix}")

def _print_fail(check: str, detail: str, fix: str) -> None:
    print(f"  [  FAIL  ]  {check}")
    if detail: print(f"              Got  : {detail}")
    print(f"              Fix  : {fix}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Validate Kerala 2018 demo event in PostGIS")
    parser.add_argument(
        "--db", default=_DEFAULT_DSN,
        help="PostgreSQL DSN"
    )
    args = parser.parse_args()
    sys.exit(run(args.db))
