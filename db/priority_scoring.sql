-- ============================================================
-- OrbitalMind — Priority Scoring Function
-- ============================================================
-- Creates a PostgreSQL stored function that:
--   1. Selects disaster-type-specific scoring weights
--   2. Runs the infrastructure overlay (hospitals, schools, bridges, roads)
--   3. Applies: Score = w1×pop_score + w2×infra_score + w3×access_score + w4×intensity_score
--   4. Assigns priority_rank via ROW_NUMBER() DESC
--   5. INSERTs results into priority_results (with scoring_weights JSONB snapshot)
--   6. RETURNs the full ranked zone list
--
-- Run:
--   psql -U postgres -d orbitalmind -f db/priority_scoring.sql
--
-- Then call:
--   SELECT * FROM calculate_priority_score('<event-uuid>', 'flood');
--   -- or look up disaster_type automatically:
--   SELECT * FROM calculate_priority_score('<event-uuid>');
-- ============================================================


-- ============================================================
-- FUNCTION: calculate_priority_score
-- ============================================================
CREATE OR REPLACE FUNCTION calculate_priority_score(
    p_event_id      UUID,
    p_disaster_type TEXT DEFAULT NULL   -- if NULL, looked up from disaster_events
)
RETURNS TABLE (
    admin_zone_id       UUID,
    zone_name           TEXT,
    population          BIGINT,
    hospitals_affected  BIGINT,
    schools_affected    BIGINT,
    bridges_at_risk     BIGINT,
    roads_disrupted_pct DOUBLE PRECISION,
    overlap_area_km2    DOUBLE PRECISION,
    avg_confidence      DOUBLE PRECISION,
    population_score    DOUBLE PRECISION,
    infra_score         DOUBLE PRECISION,
    access_score        DOUBLE PRECISION,
    intensity_score     DOUBLE PRECISION,
    priority_score      DOUBLE PRECISION,
    priority_rank       INTEGER
)
LANGUAGE plpgsql
SECURITY DEFINER   -- runs with owner privileges for planet_osm_* access
AS $$
DECLARE
    v_disaster_type TEXT;
    v_w_pop         DOUBLE PRECISION;
    v_w_infra       DOUBLE PRECISION;
    v_w_access      DOUBLE PRECISION;
    v_w_intensity   DOUBLE PRECISION;
    v_weights       JSONB;
BEGIN
    -- ── Resolve disaster_type ────────────────────────────────────────────
    IF p_disaster_type IS NULL THEN
        SELECT de.disaster_type
        INTO   v_disaster_type
        FROM   disaster_events de
        WHERE  de.event_id = p_event_id;

        IF NOT FOUND THEN
            RAISE EXCEPTION
                'Event % not found in disaster_events. '
                'Run: psql -f db/schema.sql to seed demo events.',
                p_event_id;
        END IF;
    ELSE
        v_disaster_type := lower(trim(p_disaster_type));
    END IF;

    -- ── Validate event exists ────────────────────────────────────────────
    PERFORM 1 FROM disaster_events WHERE event_id = p_event_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Event % not found in disaster_events.', p_event_id;
    END IF;

    -- ── Select weights by disaster type ──────────────────────────────────
    -- Full weight rationale: see docs/scoring_weights.md
    CASE v_disaster_type
        WHEN 'flood' THEN
            -- Flood: population & infrastructure dominate.
            -- Population (0.40): dense low-lying areas face direct inundation.
            -- Infra (0.30): hospitals and bridges become inaccessible in floods.
            -- Access (0.20): roads cut off rescue operations for days.
            -- Intensity (0.10): SAR confidence already encoded in zone selection.
            v_w_pop      := 0.40;
            v_w_infra    := 0.30;
            v_w_access   := 0.20;
            v_w_intensity:= 0.10;

        WHEN 'wildfire' THEN
            -- Wildfire: access & intensity dominate.
            -- Population (0.25): fires start in forests, spread to settlements.
            -- Infra (0.20): structures burn but are often not rescue-blocking.
            -- Access (0.30): evacuation routes critically threatened.
            -- Intensity (0.25): dNBR severity (high/low) directly affects response effort.
            v_w_pop      := 0.25;
            v_w_infra    := 0.20;
            v_w_access   := 0.30;
            v_w_intensity:= 0.25;

        WHEN 'landslide' THEN
            -- Landslide: access dominates — road blockage is the defining impact.
            -- Population (0.30): mountain settlements moderately dense.
            -- Infra (0.25): bridges on mountain roads frequently destroyed.
            -- Access (0.35): landslides block highway arteries (NH-3, NH-5).
            -- Intensity (0.10): SAR amplitude change is a reliable binary indicator.
            v_w_pop      := 0.30;
            v_w_infra    := 0.25;
            v_w_access   := 0.35;
            v_w_intensity:= 0.10;

        WHEN 'cyclone' THEN
            -- Cyclone: population & access balanced.
            -- Population (0.35): coastal communities dense and highly exposed.
            -- Infra (0.25): storm surge floods hospitals near coast.
            -- Access (0.25): storm surge and debris block coastal roads.
            -- Intensity (0.15): wind speed tier directly affects structural damage.
            v_w_pop      := 0.35;
            v_w_infra    := 0.25;
            v_w_access   := 0.25;
            v_w_intensity:= 0.15;

        WHEN 'earthquake' THEN
            -- Earthquake: infrastructure dominates (structural collapse).
            -- Population (0.30): dense urban cores suffer most casualties.
            -- Infra (0.40): hospitals may collapse — the highest risk metric.
            -- Access (0.20): rubble blocks roads but less than other disasters.
            -- Intensity (0.10): InSAR coherence loss reliable for extent mapping.
            v_w_pop      := 0.30;
            v_w_infra    := 0.40;
            v_w_access   := 0.20;
            v_w_intensity:= 0.10;

        ELSE
            RAISE EXCEPTION
                'Unknown disaster_type: %. '
                'Valid values: flood, wildfire, landslide, cyclone, earthquake.',
                v_disaster_type;
    END CASE;

    -- Build JSONB weights snapshot for audit trail
    v_weights := jsonb_build_object(
        'population', v_w_pop,
        'infra',      v_w_infra,
        'access',     v_w_access,
        'intensity',  v_w_intensity
    );

    -- ── Clear previous results for this event ────────────────────────────
    DELETE FROM priority_results WHERE event_id = p_event_id;

    -- ── Main scoring query ───────────────────────────────────────────────
    -- Uses a data-modifying CTE (persisted) that INSERTs results while
    -- the final SELECT returns the same data to the caller.
    -- Per PostgreSQL docs, data-modifying CTEs always execute to completion
    -- regardless of whether their output is referenced in the final SELECT.
    RETURN QUERY
    WITH

    -- Step 1: affected zones for this event (both CRS for later joins)
    event_zones AS (
        SELECT
            az.zone_id,
            az.geom                     AS geom_4326,
            ST_Transform(az.geom, 3857) AS geom_3857,
            az.confidence,
            az.area_km2
        FROM affected_zones az
        WHERE az.event_id = p_event_id
    ),

    -- Step 2: union of all affected zones → single geometry for fast intersection
    event_union AS (
        SELECT
            ST_Union(ez.geom_3857) AS union_3857,
            ST_Union(ez.geom_4326) AS union_4326
        FROM event_zones ez
    ),

    -- Step 3: admin zones overlapping the event area
    overlapping_admin AS (
        SELECT
            adm.zone_id                         AS admin_zone_id,
            adm.name                            AS zone_name,
            COALESCE(adm.population, 0)         AS population,
            adm.geom                            AS admin_geom_4326,
            ST_Transform(adm.geom, 3857)        AS admin_geom_3857,
            ST_Intersection(
                ST_Transform(adm.geom, 3857),
                eu.union_3857
            )                                   AS intersect_geom_3857
        FROM admin_zones adm, event_union eu
        WHERE
            ST_Intersects(
                ST_Transform(adm.geom, 3857),
                eu.union_3857
            )
            AND NOT ST_IsEmpty(
                ST_Intersection(
                    ST_Transform(adm.geom, 3857),
                    eu.union_3857
                )
            )
            -- Require polygon intersection (not touching edges only)
            AND ST_Dimension(
                ST_Intersection(
                    ST_Transform(adm.geom, 3857),
                    eu.union_3857
                )
            ) = 2
    ),

    -- Step 4: hospital counts (amenity=hospital inside affected area)
    hospital_counts AS (
        SELECT
            oa.admin_zone_id,
            COUNT(p.osm_id) AS cnt
        FROM overlapping_admin oa
        LEFT JOIN planet_osm_point p
            ON  p.amenity = 'hospital'
            AND ST_Within(p.way, oa.intersect_geom_3857)
        GROUP BY oa.admin_zone_id
    ),

    -- Step 5: school counts (school/college/university inside affected area)
    school_counts AS (
        SELECT
            oa.admin_zone_id,
            COUNT(p.osm_id) AS cnt
        FROM overlapping_admin oa
        LEFT JOIN planet_osm_point p
            ON  p.amenity IN ('school', 'college', 'university')
            AND ST_Within(p.way, oa.intersect_geom_3857)
        GROUP BY oa.admin_zone_id
    ),

    -- Step 6: bridge counts (bridge=yes roads crossing the affected zone)
    bridge_counts AS (
        SELECT
            oa.admin_zone_id,
            COUNT(l.osm_id) AS cnt
        FROM overlapping_admin oa
        LEFT JOIN planet_osm_line l
            ON  l.bridge  = 'yes'
            AND l.highway IS NOT NULL
            AND ST_Intersects(l.way, oa.intersect_geom_3857)
        GROUP BY oa.admin_zone_id
    ),

    -- Step 7: road disruption fraction
    --   roads_disrupted_pct = disrupted_km / total_km in district  [0, 1]
    road_stats AS (
        SELECT
            oa.admin_zone_id,
            COALESCE(SUM(
                ST_Length(ST_Intersection(l.way, oa.admin_geom_3857))
            ), 0.0) AS total_road_m,
            COALESCE(SUM(
                CASE
                    WHEN NOT ST_IsEmpty(oa.intersect_geom_3857)
                         AND ST_Intersects(l.way, oa.intersect_geom_3857)
                    THEN ST_Length(ST_Intersection(l.way, oa.intersect_geom_3857))
                    ELSE 0.0
                END
            ), 0.0) AS disrupted_road_m
        FROM overlapping_admin oa
        LEFT JOIN planet_osm_line l
            ON  l.highway IS NOT NULL
            AND l.bridge  IS DISTINCT FROM 'yes'
            AND ST_Intersects(l.way, oa.admin_geom_3857)
        GROUP BY oa.admin_zone_id
    ),

    -- Step 8: average confidence of affected zones per admin district
    zone_confidence AS (
        SELECT
            oa.admin_zone_id,
            AVG(ez.confidence) AS avg_conf
        FROM overlapping_admin oa
        JOIN event_zones ez
            ON ST_Intersects(ez.geom_4326, oa.admin_geom_4326)
        GROUP BY oa.admin_zone_id
    ),

    -- Step 9: assemble raw overlay row per district
    overlay AS (
        SELECT
            oa.admin_zone_id,
            oa.zone_name,
            oa.population,
            COALESCE(hc.cnt, 0)     AS hospitals_affected,
            COALESCE(sc.cnt, 0)     AS schools_affected,
            COALESCE(bc.cnt, 0)     AS bridges_at_risk,
            CASE
                WHEN COALESCE(rs.total_road_m, 0) = 0 THEN 0.0
                ELSE LEAST(rs.disrupted_road_m / rs.total_road_m, 1.0)
            END                     AS roads_disrupted_pct,
            ROUND(
                (ST_Area(
                    ST_Transform(oa.intersect_geom_3857, 4326)::geography
                ) / 1e6)::NUMERIC, 3
            )::DOUBLE PRECISION     AS overlap_area_km2,
            COALESCE(zc.avg_conf, 0.5) AS avg_confidence
        FROM overlapping_admin oa
        LEFT JOIN hospital_counts hc ON oa.admin_zone_id = hc.admin_zone_id
        LEFT JOIN school_counts   sc ON oa.admin_zone_id = sc.admin_zone_id
        LEFT JOIN bridge_counts   bc ON oa.admin_zone_id = bc.admin_zone_id
        LEFT JOIN road_stats      rs ON oa.admin_zone_id = rs.admin_zone_id
        LEFT JOIN zone_confidence zc ON oa.admin_zone_id = zc.admin_zone_id
    ),

    -- Step 10: normalisation denominators (per-event maxima)
    max_vals AS (
        SELECT
            -- max population among affected districts for normalisation
            NULLIF(MAX(o.population), 0)::DOUBLE PRECISION AS max_pop,
            -- max weighted infra count (hospitals×3 + schools×2 + bridges×1)
            NULLIF(
                MAX(o.hospitals_affected * 3 + o.schools_affected * 2 + o.bridges_at_risk),
                0
            )::DOUBLE PRECISION                            AS max_infra
        FROM overlay o
    ),

    -- Step 11: compute individual component scores [0, 1]
    scored AS (
        SELECT
            o.*,
            -- pop_score: fraction of max district population
            CASE WHEN mv.max_pop IS NULL THEN 0.0
                 ELSE o.population::DOUBLE PRECISION / mv.max_pop
            END                                         AS pop_score,
            -- infra_score: weighted critical infrastructure count, normalised
            CASE WHEN mv.max_infra IS NULL THEN 0.0
                 ELSE (o.hospitals_affected * 3.0
                     + o.schools_affected   * 2.0
                     + o.bridges_at_risk    * 1.0) / mv.max_infra
            END                                         AS inf_score,
            -- access_score: fraction of roads disrupted (higher = less accessible)
            o.roads_disrupted_pct                       AS acc_score,
            -- intensity_score: average SAR/satellite detection confidence
            o.avg_confidence                            AS int_score
        FROM overlay o, max_vals mv
    ),

    -- Step 12: composite score + rank
    ranked AS (
        SELECT
            s.*,
            ROUND(
                (v_w_pop       * s.pop_score
               + v_w_infra     * s.inf_score
               + v_w_access    * s.acc_score
               + v_w_intensity * s.int_score)::NUMERIC, 6
            )::DOUBLE PRECISION                         AS final_score,
            ROW_NUMBER() OVER (
                ORDER BY
                    (v_w_pop       * s.pop_score
                   + v_w_infra     * s.inf_score
                   + v_w_access    * s.acc_score
                   + v_w_intensity * s.int_score) DESC
            )::INTEGER                                  AS rank_num
        FROM scored s
    ),

    -- Step 13: persist to priority_results (side-effect CTE)
    -- This INSERT runs to completion even if the final SELECT references it or not.
    persisted AS (
        INSERT INTO priority_results (
            event_id,
            disaster_type,
            admin_zone_id,
            priority_score,
            priority_rank,
            population_score,
            infra_score,
            access_score,
            intensity_score,
            scoring_weights,
            hospitals_affected,
            schools_affected,
            bridges_affected,
            road_segments_blocked
        )
        SELECT
            p_event_id,
            v_disaster_type,
            r.admin_zone_id,
            r.final_score,
            r.rank_num,
            r.pop_score,
            r.inf_score,
            r.acc_score,
            r.int_score,
            v_weights,
            r.hospitals_affected::INTEGER,
            r.schools_affected::INTEGER,
            r.bridges_at_risk::INTEGER,
            0   -- road_segments_blocked: length-based pct used instead of count
        FROM ranked r
        RETURNING result_id
    )

    -- Final SELECT: return ranked results to caller
    -- 'persisted' executes independently due to PostgreSQL data-modifying CTE rules.
    SELECT
        r.admin_zone_id,
        r.zone_name,
        r.population,
        r.hospitals_affected,
        r.schools_affected,
        r.bridges_at_risk,
        r.roads_disrupted_pct,
        r.overlap_area_km2,
        r.avg_confidence,
        r.pop_score         AS population_score,
        r.inf_score         AS infra_score,
        r.acc_score         AS access_score,
        r.int_score         AS intensity_score,
        r.final_score       AS priority_score,
        r.rank_num          AS priority_rank
    FROM ranked r
    -- Reference persisted to guarantee INSERT executes (no-op if empty)
    WHERE EXISTS (SELECT 1 FROM persisted LIMIT 1) OR TRUE
    ORDER BY r.rank_num;

END;
$$;


-- ============================================================
-- HELPER: get_event_priority_zones(event_slug TEXT)
-- ============================================================
-- Convenience wrapper that accepts an event slug (e.g. 'kerala_2018')
-- instead of a UUID.  Looks up the UUID from disaster_events.
-- ============================================================
CREATE OR REPLACE FUNCTION get_event_priority_zones(p_event_slug TEXT)
RETURNS TABLE (
    admin_zone_id       UUID,
    zone_name           TEXT,
    population          BIGINT,
    hospitals_affected  BIGINT,
    schools_affected    BIGINT,
    bridges_at_risk     BIGINT,
    roads_disrupted_pct DOUBLE PRECISION,
    overlap_area_km2    DOUBLE PRECISION,
    avg_confidence      DOUBLE PRECISION,
    population_score    DOUBLE PRECISION,
    infra_score         DOUBLE PRECISION,
    access_score        DOUBLE PRECISION,
    intensity_score     DOUBLE PRECISION,
    priority_score      DOUBLE PRECISION,
    priority_rank       INTEGER
)
LANGUAGE plpgsql AS $$
DECLARE
    v_event_id UUID;
    v_slug     TEXT := lower(replace(p_event_slug, '-', '_'));
BEGIN
    SELECT de.event_id
    INTO   v_event_id
    FROM   disaster_events de
    WHERE
        lower(replace(de.region, ' ', '_')) || '_'
        || EXTRACT(YEAR FROM de.date_start)::TEXT = v_slug
        OR lower(replace(de.display_name, ' ', '_')) LIKE '%' || v_slug || '%'
    ORDER BY de.date_start DESC
    LIMIT 1;

    IF NOT FOUND THEN
        RAISE EXCEPTION
            'No event found for slug "%". '
            'Check: SELECT event_id, display_name FROM disaster_events;',
            p_event_slug;
    END IF;

    RETURN QUERY SELECT * FROM calculate_priority_score(v_event_id);
END;
$$;


-- ============================================================
-- GRANT permissions (if running as non-superuser)
-- ============================================================
-- GRANT EXECUTE ON FUNCTION calculate_priority_score(UUID, TEXT) TO orbitalmind_app;
-- GRANT EXECUTE ON FUNCTION get_event_priority_zones(TEXT)         TO orbitalmind_app;


-- ============================================================
-- QUICK TEST
-- ============================================================
-- Run after installing schema + seeding demo events:
--
--   SELECT zone_name, priority_rank, priority_score,
--          hospitals_affected, roads_disrupted_pct
--   FROM get_event_priority_zones('kerala_2018')
--   ORDER BY priority_rank;
-- ============================================================
