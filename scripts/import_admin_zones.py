"""
OrbitalMind — Kerala District Boundaries Importer
===================================================
Fetches Kerala district boundary GeoJSON from the Datameet India GIS
repository and loads it into the ``admin_zones`` PostGIS table along
with 2011 Census population figures.

Usage
-----
    python scripts/import_admin_zones.py

    # Custom database URL:
    python scripts/import_admin_zones.py --db "postgresql://user:pass@host/db"

    # Overwrite existing records:
    python scripts/import_admin_zones.py --replace

Requirements
------------
    pip install geopandas sqlalchemy psycopg2-binary requests

Output
------
    [OK] Downloaded Kerala districts GeoJSON (14 districts)
    [OK] Inserted 14 districts into admin_zones
    [OK] Total population loaded: 33,406,061
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Repo root on path
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# ---------------------------------------------------------------------------
# 2011 Census of India — Kerala district populations
# Source: Office of the Registrar General & Census Commissioner, India
# https://censusindia.gov.in/census.website/data/census-tables
# ---------------------------------------------------------------------------
KERALA_DISTRICT_POPULATION_2011: dict[str, int] = {
    "Thiruvananthapuram": 3_301_427,
    "Kollam":             2_635_375,
    "Pathanamthitta":     1_197_412,
    "Alappuzha":          2_127_789,
    "Kottayam":           1_974_551,
    "Idukki":             1_108_974,
    "Ernakulam":          3_282_388,
    "Thrissur":           3_121_200,
    "Palakkad":           2_809_934,
    "Malappuram":         4_112_920,
    "Kozhikode":          3_086_293,
    "Wayanad":              816_558,
    "Kannur":             2_523_003,
    "Kasaragod":          1_307_375,
}
TOTAL_KERALA_POPULATION = sum(KERALA_DISTRICT_POPULATION_2011.values())

# Name normalisation map: GeoJSON names → census names
# (Datameet sometimes uses different spellings)
_NAME_ALIASES: dict[str, str] = {
    "Trivandrum":         "Thiruvananthapuram",
    "Alleppey":           "Alappuzha",
    "Trichur":            "Thrissur",
    "Calicut":            "Kozhikode",
    "Quilon":             "Kollam",
    "Palghat":            "Palakkad",
    "Cannanore":          "Kannur",
    "Kasargod":           "Kasaragod",
    "Ernakulam":          "Ernakulam",
    "Idukki":             "Idukki",
    "Kottayam":           "Kottayam",
    "Malappuram":         "Malappuram",
    "Pathanamthitta":     "Pathanamthitta",
    "Wayanad":            "Wayanad",
}

# ---------------------------------------------------------------------------
# Source URLs (tried in order; first success wins)
# ---------------------------------------------------------------------------
_GEOJSON_URLS: list[str] = [
    # Datameet India Maps — primary
    "https://raw.githubusercontent.com/datameet/maps/master/Districts/Kerala.geojson",
    # Fallback: alternative mirror
    "https://raw.githubusercontent.com/unocha/hdx-data/master/india/admin2/Kerala.geojson",
]

# Default PostgreSQL connection string
_DEFAULT_DB_URL = "postgresql://postgres:postgres@localhost:5432/orbitalmind"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalise_district_name(raw: str) -> str:
    """Normalise a district name to match the census dict keys."""
    cleaned = raw.strip().title()
    return _NAME_ALIASES.get(cleaned, cleaned)


def _fetch_geojson(urls: list[str]) -> dict:
    """Try each URL in order and return the parsed GeoJSON dict.

    Parameters
    ----------
    urls : list[str]
        Candidate URLs to try.

    Returns
    -------
    dict
        Parsed GeoJSON FeatureCollection.

    Raises
    ------
    RuntimeError
        If all URLs fail.
    """
    import requests  # type: ignore[import]

    for url in urls:
        try:
            print(f"  [GET]  {url}")
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            n = len(data.get("features", []))
            print(f"  [OK]   Downloaded {n} features")
            return data
        except Exception as exc:
            print(f"  [WARN] Failed ({exc.__class__.__name__}: {exc})")

    raise RuntimeError(
        "All GeoJSON download URLs failed.\n"
        "Download manually from:\n"
        "  https://raw.githubusercontent.com/datameet/maps/master/Districts/Kerala.geojson\n"
        "Then place the file at: data/osm/Kerala.geojson\n"
        "And run: python scripts/import_admin_zones.py --local data/osm/Kerala.geojson"
    )


def _geojson_to_geodataframe(geojson: dict):
    """Convert a GeoJSON FeatureCollection to a GeoDataFrame.

    Adds ``name`` (normalised), ``population``, ``admin_level``,
    ``state``, and ``country`` columns.

    Returns
    -------
    geopandas.GeoDataFrame
    """
    import geopandas as gpd  # type: ignore[import]
    from shapely.geometry import shape, mapping, MultiPolygon, Polygon

    rows = []
    for feat in geojson.get("features", []):
        props = feat.get("properties") or {}
        geom  = feat.get("geometry")

        # Extract raw name — Datameet uses DISTRICT or NAME_2 or dt_name
        raw_name = (
            props.get("DISTRICT")
            or props.get("NAME_2")
            or props.get("dt_name")
            or props.get("name")
            or props.get("Name")
            or "Unknown"
        )
        name = _normalise_district_name(str(raw_name))

        # Convert to Shapely and ensure MultiPolygon
        sh_geom = shape(geom)
        if isinstance(sh_geom, Polygon):
            sh_geom = MultiPolygon([sh_geom])

        # Area in km² (using geographic CRS approximation)
        import math
        centroid    = sh_geom.centroid
        lat_rad     = math.radians(centroid.y)
        km_per_deg_lon = 111.0 * math.cos(lat_rad)
        km_per_deg_lat = 111.0
        bounds      = sh_geom.bounds
        area_km2    = (
            abs(bounds[2] - bounds[0]) * km_per_deg_lon *
            abs(bounds[3] - bounds[1]) * km_per_deg_lat
        )

        population = KERALA_DISTRICT_POPULATION_2011.get(name)

        rows.append({
            "name":        name,
            "state":       "Kerala",
            "country":     "India",
            "admin_level": 6,
            "population":  population,
            "area_km2":    round(area_km2, 2),
            "geometry":    sh_geom,
        })

    gdf = gpd.GeoDataFrame(rows, crs="EPSG:4326")
    return gdf


def _insert_to_postgis(gdf, db_url: str, replace: bool) -> int:
    """Insert the GeoDataFrame into the admin_zones PostGIS table.

    Parameters
    ----------
    gdf : GeoDataFrame
        Districts with geometry and metadata.
    db_url : str
        SQLAlchemy connection URL.
    replace : bool
        If True, delete existing Kerala records before inserting.

    Returns
    -------
    int
        Number of rows inserted.
    """
    from sqlalchemy import create_engine, text  # type: ignore[import]
    import geopandas as gpd                     # type: ignore[import]

    engine = create_engine(db_url)

    with engine.connect() as conn:
        # Verify PostGIS is installed
        try:
            result = conn.execute(text("SELECT PostGIS_Full_Version()"))
            version = result.fetchone()[0].split(" ")[0]
            print(f"  [DB]   PostGIS detected: {version}")
        except Exception as exc:
            raise RuntimeError(
                f"PostGIS not available in the database: {exc}\n"
                "Run: psql -U postgres -d orbitalmind -c \"CREATE EXTENSION postgis;\""
            )

        # Verify admin_zones table exists
        result = conn.execute(text(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_name = 'admin_zones')"
        ))
        if not result.scalar():
            raise RuntimeError(
                "admin_zones table not found.\n"
                "Run: psql -U postgres -d orbitalmind -f db/schema.sql"
            )

        # Optionally clear existing Kerala records
        if replace:
            deleted = conn.execute(text(
                "DELETE FROM admin_zones WHERE state = 'Kerala'"
            ))
            print(f"  [DB]   Deleted {deleted.rowcount} existing Kerala records")
            conn.commit()

        # Check for existing records
        result = conn.execute(text(
            "SELECT COUNT(*) FROM admin_zones WHERE state = 'Kerala'"
        ))
        existing = result.scalar()
        if existing > 0 and not replace:
            print(f"  [SKIP] {existing} Kerala districts already in admin_zones.")
            print("         Use --replace to overwrite.")
            return 0

    # Insert via geopandas.to_postgis
    gdf.to_postgis(
        name       = "admin_zones",
        con        = engine,
        if_exists  = "append",
        index      = False,
        dtype      = None,
    )
    return len(gdf)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(
    db_url:     str  = _DEFAULT_DB_URL,
    replace:    bool = False,
    local_path: str | None = None,
) -> None:
    """Import Kerala district boundaries into admin_zones.

    Parameters
    ----------
    db_url : str
        SQLAlchemy PostgreSQL URL.
    replace : bool
        Delete existing Kerala rows before inserting.
    local_path : str or None
        If provided, load GeoJSON from this local file instead of downloading.
    """
    try:
        import geopandas  # type: ignore[import]
    except ImportError:
        print("[ERROR] geopandas not installed. Run: pip install geopandas")
        sys.exit(1)

    print()
    print("=" * 60)
    print("  OrbitalMind — Kerala Admin Zones Importer")
    print("=" * 60)
    print(f"  Database : {db_url}")
    print(f"  Replace  : {replace}")
    print()

    # ── Load GeoJSON ──────────────────────────────────────────────────────
    if local_path:
        print(f"  [LOCAL] Loading from: {local_path}")
        with open(local_path, encoding="utf-8") as fh:
            geojson = json.load(fh)
        n = len(geojson.get("features", []))
        print(f"  [OK]   Loaded {n} features from local file")
    else:
        print("  Fetching Kerala district GeoJSON ...")
        geojson = _fetch_geojson(_GEOJSON_URLS)

    # ── Build GeoDataFrame ────────────────────────────────────────────────
    print("\n  Building GeoDataFrame ...")
    gdf = _geojson_to_geodataframe(geojson)
    print(f"  Districts found : {len(gdf)}")

    pop_loaded = 0
    pop_missing = []
    for _, row in gdf.iterrows():
        if row["population"]:
            pop_loaded += row["population"]
        else:
            pop_missing.append(row["name"])

    print(f"  Pop data loaded : {pop_loaded:,}")
    if pop_missing:
        print(f"  [WARN] No census data for: {pop_missing}")
        print(f"         (Districts not in the 2011 census mapping)")
    print()

    # ── Print district table ──────────────────────────────────────────────
    print(f"  {'District':<20}  {'Population':>12}  {'Area km²':>10}")
    print("  " + "-" * 48)
    for _, row in gdf.sort_values("population", ascending=False).iterrows():
        pop_str  = f"{row['population']:,}" if row["population"] else "N/A"
        area_str = f"{row['area_km2']:.0f}" if row["area_km2"] else "N/A"
        print(f"  {row['name']:<20}  {pop_str:>12}  {area_str:>10}")
    print()

    # ── Insert to PostGIS ─────────────────────────────────────────────────
    print("  Inserting into admin_zones ...")
    n_inserted = _insert_to_postgis(gdf, db_url, replace)

    print()
    print("=" * 60)
    if n_inserted > 0:
        print(f"  [OK]   {n_inserted} districts inserted into admin_zones")
        print(f"  [OK]   Total population loaded: {pop_loaded:,}")
        print(f"  [OK]   Expected total: {TOTAL_KERALA_POPULATION:,}")
    else:
        print("  [SKIP] No rows inserted (already exist).")
    print("=" * 60 + "\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Import Kerala district boundaries into OrbitalMind admin_zones"
    )
    parser.add_argument(
        "--db",
        default = _DEFAULT_DB_URL,
        help    = "SQLAlchemy PostgreSQL URL (default: postgresql://postgres:postgres@localhost:5432/orbitalmind)",
    )
    parser.add_argument(
        "--replace", "-r",
        action  = "store_true",
        help    = "Delete existing Kerala records before inserting",
    )
    parser.add_argument(
        "--local",
        metavar = "FILE",
        default = None,
        help    = "Load GeoJSON from a local file instead of downloading",
    )
    args = parser.parse_args()
    run(db_url=args.db, replace=args.replace, local_path=args.local)
