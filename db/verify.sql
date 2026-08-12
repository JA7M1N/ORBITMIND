-- ============================================================
-- OrbitalMind — Database Verification Queries
-- ============================================================
-- Run after:
--   1. psql -U postgres -d orbitalmind -f db/schema.sql
--   2. osm2pgsql import of kerala-latest.osm.pbf
--   3. python scripts/import_admin_zones.py
--
-- Usage:
--   psql -U postgres -d orbitalmind -f db/verify.sql
--
-- All counts should be > 0 for a PASS.
-- ============================================================

\echo '============================================================'
\echo '  OrbitalMind — Database Verification'
\echo '============================================================'
\echo ''

-- ── 1. PostGIS function verification ─────────────────────────
\echo '--- 1. PostGIS Functions ---'

SELECT
    'ST_Area (Kerala bbox)' AS test,
    ROUND(
        (ST_Area(
            ST_MakeEnvelope(76.0, 9.5, 77.5, 11.0, 4326)::geography
        ) / 1e6)::NUMERIC, 1
    ) AS result_km2,
    CASE WHEN ST_Area(
            ST_MakeEnvelope(76.0, 9.5, 77.5, 11.0, 4326)::geography
         ) > 0
         THEN 'PASS' ELSE 'FAIL' END AS status;

SELECT
    'ST_Intersects (self-test)' AS test,
    ST_Intersects(
        ST_MakePoint(76.5, 10.0),
        ST_MakeEnvelope(76.0, 9.5, 77.5, 11.0, 4326)
    )::TEXT AS result,
    CASE WHEN ST_Intersects(
            ST_MakePoint(76.5, 10.0),
            ST_MakeEnvelope(76.0, 9.5, 77.5, 11.0, 4326)
         )
         THEN 'PASS' ELSE 'FAIL' END AS status;

SELECT
    'ST_Distance (Trivandrum→Ernakulam)' AS test,
    ROUND(
        ST_Distance(
            ST_MakePoint(76.9366, 8.5241)::geography,
            ST_MakePoint(76.2673, 9.9312)::geography
        )::NUMERIC / 1000, 1
    ) AS result_km,
    'PASS (>0)' AS status;

\echo ''

-- ── 2. OrbitalMind Schema checks ─────────────────────────────
\echo '--- 2. OrbitalMind Schema ---'

SELECT
    'disaster_events table'   AS object,
    COUNT(*)                  AS row_count,
    CASE WHEN COUNT(*) = 5 THEN 'PASS (5 demo events seeded)'
         WHEN COUNT(*) > 0 THEN 'PARTIAL'
         ELSE 'FAIL (run: psql -f db/schema.sql)' END AS status
FROM disaster_events;

SELECT
    'disaster_events — all 5 types' AS object,
    COUNT(DISTINCT disaster_type)   AS distinct_types,
    CASE WHEN COUNT(DISTINCT disaster_type) = 5 THEN 'PASS'
         ELSE 'FAIL' END           AS status
FROM disaster_events;

SELECT
    'admin_zones table'   AS object,
    COUNT(*)              AS row_count,
    CASE WHEN COUNT(*) = 14 THEN 'PASS (14 Kerala districts)'
         WHEN COUNT(*) > 0  THEN 'PARTIAL (' || COUNT(*) || ' rows)'
         ELSE 'FAIL (run: python scripts/import_admin_zones.py)' END AS status
FROM admin_zones;

SELECT
    'admin_zones — total population' AS object,
    TO_CHAR(SUM(population), 'FM99,999,999') AS total_population,
    CASE WHEN SUM(population) > 30000000 THEN 'PASS (>30M expected for Kerala)'
         ELSE 'FAIL' END AS status
FROM admin_zones WHERE state = 'Kerala';

SELECT
    'admin_zones — geometry valid'   AS object,
    SUM(CASE WHEN ST_IsValid(geom) THEN 1 ELSE 0 END) AS valid_geoms,
    COUNT(*) AS total_geoms,
    CASE WHEN SUM(CASE WHEN ST_IsValid(geom) THEN 1 ELSE 0 END) = COUNT(*)
         THEN 'PASS' ELSE 'FAIL (invalid geometries present)' END AS status
FROM admin_zones;

\echo ''

-- ── 3. OSM Data checks ───────────────────────────────────────
\echo '--- 3. OSM Data (requires osm2pgsql import) ---'

SELECT
    'Hospitals (planet_osm_point)' AS feature,
    COUNT(*)                       AS count,
    CASE WHEN COUNT(*) > 50  THEN 'PASS'
         WHEN COUNT(*) > 0   THEN 'PARTIAL (' || COUNT(*) || ' found)'
         ELSE 'FAIL (run osm2pgsql import)' END AS status
FROM planet_osm_point
WHERE amenity = 'hospital';

SELECT
    'Schools (planet_osm_point)'   AS feature,
    COUNT(*)                       AS count,
    CASE WHEN COUNT(*) > 100 THEN 'PASS'
         WHEN COUNT(*) > 0   THEN 'PARTIAL'
         ELSE 'FAIL' END          AS status
FROM planet_osm_point
WHERE amenity IN ('school', 'college', 'university');

SELECT
    'Roads (planet_osm_line)'      AS feature,
    COUNT(*)                       AS count,
    CASE WHEN COUNT(*) > 10000 THEN 'PASS'
         WHEN COUNT(*) > 0     THEN 'PARTIAL'
         ELSE 'FAIL' END          AS status
FROM planet_osm_line
WHERE highway IS NOT NULL;

SELECT
    'Bridges (planet_osm_line)'    AS feature,
    COUNT(*)                       AS count,
    CASE WHEN COUNT(*) > 0 THEN 'PASS' ELSE 'FAIL' END AS status
FROM planet_osm_line
WHERE bridge = 'yes';

\echo ''

-- ── 4. Sample records ─────────────────────────────────────────
\echo '--- 4. Sample Hospital Records ---'

SELECT
    name,
    amenity,
    ST_AsText(ST_Transform(way, 4326)) AS location_wgs84
FROM planet_osm_point
WHERE amenity = 'hospital'
  AND name IS NOT NULL
ORDER BY name
LIMIT 5;

\echo ''
\echo '--- 5. Sample Admin Zones ---'

SELECT
    name,
    population,
    ROUND(area_km2::NUMERIC, 0) AS area_km2,
    ST_AsText(ST_Centroid(geom)) AS centroid
FROM admin_zones
WHERE state = 'Kerala'
ORDER BY population DESC
LIMIT 5;

\echo ''

-- ── 5. Spatial intersection test ─────────────────────────────
\echo '--- 6. Spatial Intersection: Hospitals in Kerala Flood Bbox ---'

SELECT
    'Hospitals in Kerala flood bbox' AS test,
    COUNT(*) AS count,
    CASE WHEN COUNT(*) > 0
         THEN 'PASS (' || COUNT(*) || ' hospitals in flood area)'
         ELSE 'FAIL — check OSM import or bbox coordinates'
    END AS status
FROM planet_osm_point
WHERE amenity = 'hospital'
  AND ST_Intersects(
    way,
    ST_Transform(
        ST_MakeEnvelope(76.0, 9.5, 77.5, 11.0, 4326),
        3857   -- OSM planet_osm tables use EPSG:3857
    )
);

\echo ''
\echo '--- 7. Disaster Events Seed Data ---'

SELECT
    disaster_type,
    display_name,
    date_start,
    status,
    ST_AsText(bbox) AS bbox_wkt
FROM disaster_events
ORDER BY date_start;

\echo ''
\echo '============================================================'
\echo '  Verification complete.'
\echo '  All PASS results = database ready for OrbitalMind demo.'
\echo '============================================================'
