-- ============================================================
-- OrbitalMind — Infrastructure Overlay Query
-- ============================================================
-- Parameterized query: $1 = event_id (UUID)
--
-- Returns per-admin-zone infrastructure impact counts for any
-- disaster type.  Works by spatially intersecting:
--   - affected_zones (our ML output, EPSG:4326)
--   - admin_zones    (district boundaries, EPSG:4326)
--   - planet_osm_*   (OSM data from osm2pgsql, EPSG:3857)
--
-- Coordinate note:
--   OSM planet_osm_* tables use EPSG:3857 (Web Mercator).
--   Our tables use EPSG:4326 (WGS84).
--   All cross-table spatial ops use ST_Transform to align CRS.
--
-- Usage (psql):
--   \set event_id '550e8400-e29b-41d4-a716-446655440000'
--   \i db/infrastructure_overlay.sql
--
-- Usage (asyncpg / psycopg2):
--   await conn.fetch(open('db/infrastructure_overlay.sql').read(), event_uuid)
-- ============================================================

WITH

-- ── STEP 1: Fetch all affected zones for this event ───────────────────────
-- Transform to 3857 once here so downstream CTEs reuse the computation.
event_zones AS (
    SELECT
        az.zone_id,
        az.geom                              AS geom_4326,
        ST_Transform(az.geom, 3857)          AS geom_3857,
        az.confidence,
        az.area_km2,
        az.disaster_type
    FROM affected_zones az
    WHERE az.event_id = $1::UUID
),

-- ── STEP 2: Union all affected zones into one geometry per event ──────────
-- Union avoids counting infrastructure inside overlapping zones multiple times.
event_union AS (
    SELECT
        ST_Union(ez.geom_3857) AS union_3857,   -- for OSM intersections
        ST_Union(ez.geom_4326) AS union_4326    -- for admin zone intersections
    FROM event_zones ez
),

-- ── STEP 3: Find admin districts that overlap with the affected area ──────
-- Also pre-compute the intersection geometry (used repeatedly below).
overlapping_admin AS (
    SELECT
        adm.zone_id                             AS admin_zone_id,
        adm.name                                AS zone_name,
        adm.state,
        COALESCE(adm.population, 0)             AS population,
        COALESCE(adm.area_km2, 0)               AS district_area_km2,
        adm.geom                                AS admin_geom_4326,
        ST_Transform(adm.geom, 3857)            AS admin_geom_3857,
        -- Area of intersection (flood zone within this district)
        ST_Intersection(
            ST_Transform(adm.geom, 3857),
            eu.union_3857
        )                                       AS intersect_geom_3857
    FROM admin_zones adm, event_union eu
    WHERE
        -- Pre-filter using bbox before expensive ST_Intersection
        adm.geom && ST_Transform(ST_SetSRID(ST_Extent(eu.union_3857)::geometry, 3857), 4326)
        -- Confirm actual intersection
        AND ST_Intersects(
            ST_Transform(adm.geom, 3857),
            eu.union_3857
        )
        -- Drop degenerate intersections (point/line touches)
        AND NOT ST_IsEmpty(
            ST_Intersection(
                ST_Transform(adm.geom, 3857),
                eu.union_3857
            )
        )
        AND ST_Dimension(
            ST_Intersection(
                ST_Transform(adm.geom, 3857),
                eu.union_3857
            )
        ) = 2  -- require Polygon (not Point or LineString intersection)
),

-- ── STEP 4: Count hospitals in the affected zone within each district ─────
-- OSM amenity='hospital' points that fall inside the intersection geometry.
hospital_counts AS (
    SELECT
        oa.admin_zone_id,
        COUNT(p.osm_id)     AS hospitals_affected,
        COUNT(p.osm_id)
            FILTER (WHERE p.name IS NOT NULL) AS named_hospitals
    FROM overlapping_admin oa
    LEFT JOIN planet_osm_point p
        ON  p.amenity = 'hospital'
        AND ST_Within(p.way, oa.intersect_geom_3857)
    GROUP BY oa.admin_zone_id
),

-- ── STEP 5: Count schools in the affected zone ────────────────────────────
-- Includes schools, colleges, and universities (all educational infrastructure).
school_counts AS (
    SELECT
        oa.admin_zone_id,
        COUNT(p.osm_id) AS schools_affected
    FROM overlapping_admin oa
    LEFT JOIN planet_osm_point p
        ON  p.amenity IN ('school', 'college', 'university')
        AND ST_Within(p.way, oa.intersect_geom_3857)
    GROUP BY oa.admin_zone_id
),

-- ── STEP 6: Count bridges that the disaster zone intersects ───────────────
-- Bridge roads crossing through the flooded/damaged area become impassable.
bridge_counts AS (
    SELECT
        oa.admin_zone_id,
        COUNT(l.osm_id)             AS bridges_at_risk,
        -- Separate counts by road class for detailed reporting
        COUNT(l.osm_id)
            FILTER (WHERE l.highway IN ('primary', 'secondary')) AS major_bridges,
        COUNT(l.osm_id)
            FILTER (WHERE l.highway IN ('tertiary', 'residential', 'unclassified')) AS minor_bridges
    FROM overlapping_admin oa
    LEFT JOIN planet_osm_line l
        ON  l.bridge    = 'yes'
        AND l.highway   IS NOT NULL     -- only road bridges (not footways)
        AND ST_Intersects(l.way, oa.intersect_geom_3857)
    GROUP BY oa.admin_zone_id
),

-- ── STEP 7: Compute road disruption percentage ───────────────────────────
-- disrupted_pct = length_of_roads_in_affected_area / total_road_length_in_district
--
-- Uses ST_Intersection to clip road segments to district and affected boundaries.
-- ST_Length on EPSG:3857 returns metres (approximate for mid-latitudes).
road_stats AS (
    SELECT
        oa.admin_zone_id,
        -- Total road network length in this admin district (metres)
        COALESCE(SUM(
            ST_Length(ST_Intersection(l.way, oa.admin_geom_3857))
        ), 0.0)                                         AS total_road_m,
        -- Road length falling inside the affected/disaster zone (metres)
        COALESCE(SUM(
            CASE
                WHEN NOT ST_IsEmpty(oa.intersect_geom_3857)
                     AND ST_Intersects(l.way, oa.intersect_geom_3857)
                THEN ST_Length(ST_Intersection(l.way, oa.intersect_geom_3857))
                ELSE 0.0
            END
        ), 0.0)                                         AS disrupted_road_m,
        -- Count of distinct road segments disrupted (for reporting)
        COUNT(l.osm_id)
            FILTER (WHERE ST_Intersects(l.way, oa.intersect_geom_3857)) AS road_segments_disrupted
    FROM overlapping_admin oa
    LEFT JOIN planet_osm_line l
        ON  l.highway IS NOT NULL       -- any road class
        AND l.bridge  IS DISTINCT FROM 'yes'  -- bridges counted separately
        AND ST_Intersects(l.way, oa.admin_geom_3857)
    GROUP BY oa.admin_zone_id
),

-- ── STEP 8: Average ML confidence per admin district ─────────────────────
-- Used as the intensity proxy in the priority scoring formula.
zone_confidence AS (
    SELECT
        oa.admin_zone_id,
        AVG(ez.confidence)          AS avg_confidence,
        MAX(ez.confidence)          AS max_confidence,
        COUNT(ez.zone_id)           AS overlapping_zones
    FROM overlapping_admin oa
    JOIN event_zones ez
        ON ST_Intersects(ez.geom_4326, oa.admin_geom_4326)
    GROUP BY oa.admin_zone_id
)

-- ── FINAL: Assemble result row per admin zone ─────────────────────────────
SELECT
    oa.admin_zone_id,
    oa.zone_name,
    oa.state                                            AS district_state,
    oa.population,
    oa.district_area_km2,

    -- Infrastructure counts
    COALESCE(hc.hospitals_affected, 0)                  AS hospitals_affected,
    COALESCE(hc.named_hospitals,    0)                  AS named_hospitals,
    COALESCE(sc.schools_affected,   0)                  AS schools_affected,
    COALESCE(bc.bridges_at_risk,    0)                  AS bridges_at_risk,
    COALESCE(bc.major_bridges,      0)                  AS major_bridges_at_risk,

    -- Road disruption fraction [0.0, 1.0]
    CASE
        WHEN COALESCE(rs.total_road_m, 0) = 0 THEN 0.0
        ELSE LEAST(
            COALESCE(rs.disrupted_road_m, 0) / rs.total_road_m,
            1.0
        )
    END                                                 AS roads_disrupted_pct,
    COALESCE(rs.road_segments_disrupted, 0)             AS road_segments_disrupted,
    ROUND(COALESCE(rs.total_road_m,      0)::NUMERIC / 1000, 2) AS total_road_km,
    ROUND(COALESCE(rs.disrupted_road_m,  0)::NUMERIC / 1000, 2) AS disrupted_road_km,

    -- Affected area within this district (km²)
    ROUND(
        (ST_Area(
            ST_Transform(oa.intersect_geom_3857, 4326)::geography
        ) / 1e6)::NUMERIC, 3
    )::DOUBLE PRECISION                                 AS overlap_area_km2,

    -- ML confidence (intensity proxy)
    ROUND(COALESCE(zc.avg_confidence, 0.5)::NUMERIC, 4) AS avg_confidence,
    ROUND(COALESCE(zc.max_confidence, 0.5)::NUMERIC, 4) AS max_confidence,
    COALESCE(zc.overlapping_zones, 0)                   AS overlapping_zone_count,

    -- Weighted infra score (raw, before normalisation)
    (COALESCE(hc.hospitals_affected, 0) * 3
   + COALESCE(sc.schools_affected,   0) * 2
   + COALESCE(bc.bridges_at_risk,    0) * 1)            AS raw_infra_score

FROM overlapping_admin oa
LEFT JOIN hospital_counts hc ON oa.admin_zone_id = hc.admin_zone_id
LEFT JOIN school_counts   sc ON oa.admin_zone_id = sc.admin_zone_id
LEFT JOIN bridge_counts   bc ON oa.admin_zone_id = bc.admin_zone_id
LEFT JOIN road_stats      rs ON oa.admin_zone_id = rs.admin_zone_id
LEFT JOIN zone_confidence zc ON oa.admin_zone_id = zc.admin_zone_id

ORDER BY oa.population DESC NULLS LAST;
