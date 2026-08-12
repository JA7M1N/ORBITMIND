-- ============================================================
-- OrbitalMind — PostgreSQL + PostGIS Schema
-- ============================================================
-- Prerequisites:
--   CREATE DATABASE orbitalmind;
--   \c orbitalmind
--   CREATE EXTENSION IF NOT EXISTS postgis;
--
-- Run:
--   psql -U postgres -d orbitalmind -f db/schema.sql
--
-- Idempotent: safe to re-run (uses CREATE TABLE IF NOT EXISTS)
-- ============================================================

-- Extensions
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_topology;

-- Helper: auto-update updated_at column
CREATE OR REPLACE FUNCTION trigger_set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;


-- ============================================================
-- TABLE 1: disaster_events
-- ============================================================
-- One row per real or demo disaster event.
-- Links all affected_zones and priority_results for an event.
-- ============================================================
CREATE TABLE IF NOT EXISTS disaster_events (
    event_id        UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    disaster_type   TEXT         NOT NULL
                        CHECK (disaster_type IN (
                            'flood', 'wildfire', 'landslide',
                            'cyclone', 'earthquake'
                        )),
    display_name    TEXT         NOT NULL,
    region          TEXT         NOT NULL,
    state           TEXT,
    country         TEXT         NOT NULL DEFAULT 'India',
    date_start      DATE         NOT NULL,
    date_end        DATE,
    status          TEXT         NOT NULL DEFAULT 'demo'
                        CHECK (status IN ('live', 'demo', 'processing', 'complete')),
    data_source     TEXT,
    -- Bounding box of the event as a polygon (EPSG:4326)
    bbox            GEOMETRY(Polygon, 4326),
    -- Thumbnail colour for the frontend EventSelector
    thumbnail_color TEXT         DEFAULT '#6b7280',
    -- Human-readable description for the LLM narration context
    description     TEXT,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- updated_at trigger
DROP TRIGGER IF EXISTS set_updated_at_disaster_events ON disaster_events;
CREATE TRIGGER set_updated_at_disaster_events
    BEFORE UPDATE ON disaster_events
    FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();

-- Indexes
CREATE INDEX IF NOT EXISTS idx_disaster_events_disaster_type
    ON disaster_events(disaster_type);

CREATE INDEX IF NOT EXISTS idx_disaster_events_status
    ON disaster_events(status);

CREATE INDEX IF NOT EXISTS idx_disaster_events_bbox
    ON disaster_events USING GIST(bbox);

COMMENT ON TABLE disaster_events IS
    'One row per disaster event (real or demo). '
    'Parent of affected_zones and priority_results.';

COMMENT ON COLUMN disaster_events.bbox IS
    'Rough bounding box polygon in EPSG:4326 for spatial pre-filtering.';


-- ============================================================
-- TABLE 2: affected_zones
-- ============================================================
-- Individual detected zones (polygons or LineStrings) from the
-- ML pipeline or demo GeoJSON. One row per GeoJSON Feature.
--
-- intensity_metadata JSONB stores disaster-specific fields:
--   Flood:      {"water_depth_m": 2.5}
--   Wildfire:   {"severity": "high", "dnbr": 0.42}
--   Landslide:  {"slope_angle": 48, "debris_volume_m3": 12000}
--   Cyclone:    {"wind_speed_kmh": 195, "storm_surge_m": 4.2,
--                "feature_type": "storm_surge"}
--   Earthquake: {"damage_level": "destroyed", "coherence_loss": 0.71}
-- ============================================================
CREATE TABLE IF NOT EXISTS affected_zones (
    zone_id             UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id            UUID         NOT NULL
                            REFERENCES disaster_events(event_id)
                            ON DELETE CASCADE,
    disaster_type       TEXT         NOT NULL
                            CHECK (disaster_type IN (
                                'flood', 'wildfire', 'landslide',
                                'cyclone', 'earthquake'
                            )),
    -- Geometry: Polygon, MultiPolygon, or LineString (cyclone track)
    geom                GEOMETRY(Geometry, 4326) NOT NULL,
    -- ML model confidence [0.0, 1.0]
    confidence          DOUBLE PRECISION NOT NULL
                            CHECK (confidence >= 0.0 AND confidence <= 1.0),
    -- Approximate area (NULL for LineString cyclone tracks)
    area_km2            DOUBLE PRECISION
                            CHECK (area_km2 IS NULL OR area_km2 >= 0),
    -- Disaster-specific metadata fields as flexible JSONB
    intensity_metadata  JSONB        NOT NULL DEFAULT '{}',
    -- Source of this zone record
    source              TEXT         NOT NULL DEFAULT 'demo'
                            CHECK (source IN (
                                'demo', 'unet_inference', 'mock_unet_fallback',
                                'mock_nbr', 'mock_sar_dem', 'mock_insat3d',
                                'mock_surge_model', 'mock_insar', 'otsu_fallback'
                            )),
    location_label      TEXT,
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Spatial index (critical for ST_Intersects queries with OSM infra)
CREATE INDEX IF NOT EXISTS idx_affected_zones_geom
    ON affected_zones USING GIST(geom);

-- Regular indexes for filtering
CREATE INDEX IF NOT EXISTS idx_affected_zones_event_id
    ON affected_zones(event_id);

CREATE INDEX IF NOT EXISTS idx_affected_zones_disaster_type
    ON affected_zones(disaster_type);

CREATE INDEX IF NOT EXISTS idx_affected_zones_event_disaster
    ON affected_zones(event_id, disaster_type);

-- Index for confidence-based filtering (priority threshold)
CREATE INDEX IF NOT EXISTS idx_affected_zones_confidence
    ON affected_zones(confidence);

-- JSONB index for querying intensity_metadata fields
CREATE INDEX IF NOT EXISTS idx_affected_zones_intensity_metadata
    ON affected_zones USING GIN(intensity_metadata);

COMMENT ON TABLE affected_zones IS
    'Individual detected disaster zones (GeoJSON Features) from the '
    'ML pipeline. One row per feature.';

COMMENT ON COLUMN affected_zones.intensity_metadata IS
    'Disaster-specific metadata stored as JSONB. '
    'Structure varies by disaster_type — see schema docs for field reference.';

COMMENT ON COLUMN affected_zones.geom IS
    'Zone geometry in EPSG:4326. May be Polygon, MultiPolygon '
    '(most disasters) or LineString (cyclone storm track).';


-- ============================================================
-- TABLE 3: admin_zones
-- ============================================================
-- Administrative boundary polygons (districts, talukas).
-- Populated from Datameet India GIS + 2011 Census population data.
-- Used for population-weighted priority scoring.
--
-- admin_level follows OpenStreetMap / GADM convention:
--   2 = Country (India)
--   4 = State (Kerala, Maharashtra …)
--   6 = District (Alappuzha, Ernakulam …)
--   7 = Taluka / Sub-district
-- ============================================================
CREATE TABLE IF NOT EXISTS admin_zones (
    zone_id         UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    admin_level     INTEGER      NOT NULL
                        CHECK (admin_level IN (2, 4, 6, 7)),
    name            TEXT         NOT NULL,
    name_local      TEXT,         -- vernacular name (Malayalam, Hindi…)
    state           TEXT,
    country         TEXT         NOT NULL DEFAULT 'India',
    -- 2011 Census population
    population      BIGINT
                        CHECK (population IS NULL OR population >= 0),
    area_km2        DOUBLE PRECISION
                        CHECK (area_km2 IS NULL OR area_km2 > 0),
    -- MultiPolygon boundary in EPSG:4326
    geom            GEOMETRY(MultiPolygon, 4326) NOT NULL,
    -- OpenStreetMap relation ID for traceability
    osm_id          BIGINT,
    -- GADM GID for cross-referencing
    gadm_gid        TEXT,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Spatial index (used for ST_Intersects with affected_zones)
CREATE INDEX IF NOT EXISTS idx_admin_zones_geom
    ON admin_zones USING GIST(geom);

CREATE INDEX IF NOT EXISTS idx_admin_zones_state
    ON admin_zones(state);

CREATE INDEX IF NOT EXISTS idx_admin_zones_admin_level
    ON admin_zones(admin_level);

COMMENT ON TABLE admin_zones IS
    'Administrative boundary polygons with census population. '
    'Sourced from Datameet India GIS (Districts) + 2011 Census.';


-- ============================================================
-- TABLE 4: priority_results
-- ============================================================
-- Priority scores computed by the scoring engine for each
-- (event, affected_zone) pair. Stores the individual component
-- scores and the weights used at computation time (for audit).
--
-- scoring_weights JSONB structure:
--   {
--     "population": 0.40,
--     "infra":      0.30,
--     "access":     0.20,
--     "intensity":  0.10
--   }
-- ============================================================
CREATE TABLE IF NOT EXISTS priority_results (
    result_id           UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id            UUID         NOT NULL
                            REFERENCES disaster_events(event_id)
                            ON DELETE CASCADE,
    disaster_type       TEXT         NOT NULL,
    -- The specific affected zone this result scores
    zone_id             UUID
                            REFERENCES affected_zones(zone_id)
                            ON DELETE SET NULL,
    -- The admin district this zone overlaps with (nullable)
    admin_zone_id       UUID
                            REFERENCES admin_zones(zone_id)
                            ON DELETE SET NULL,

    -- Final composite priority score [0.0, 1.0]
    priority_score      DOUBLE PRECISION NOT NULL
                            CHECK (priority_score >= 0.0 AND priority_score <= 1.0),
    -- Rank within this event (1 = highest priority)
    priority_rank       INTEGER
                            CHECK (priority_rank IS NULL OR priority_rank >= 1),

    -- Component scores (each in [0.0, 1.0])
    population_score    DOUBLE PRECISION
                            CHECK (population_score IS NULL OR
                                   (population_score >= 0 AND population_score <= 1)),
    infra_score         DOUBLE PRECISION
                            CHECK (infra_score IS NULL OR
                                   (infra_score >= 0 AND infra_score <= 1)),
    access_score        DOUBLE PRECISION
                            CHECK (access_score IS NULL OR
                                   (access_score >= 0 AND access_score <= 1)),
    intensity_score     DOUBLE PRECISION
                            CHECK (intensity_score IS NULL OR
                                   (intensity_score >= 0 AND intensity_score <= 1)),

    -- Weights used at the time this result was computed (audit trail)
    scoring_weights     JSONB        NOT NULL DEFAULT
                            '{"population":0.40,"infra":0.30,"access":0.20,"intensity":0.10}',

    -- Infra counts from OSM spatial intersection
    hospitals_affected  INTEGER      NOT NULL DEFAULT 0 CHECK (hospitals_affected >= 0),
    schools_affected    INTEGER      NOT NULL DEFAULT 0 CHECK (schools_affected >= 0),
    bridges_affected    INTEGER      NOT NULL DEFAULT 0 CHECK (bridges_affected >= 0),
    road_segments_blocked INTEGER    NOT NULL DEFAULT 0 CHECK (road_segments_blocked >= 0),

    -- LLM-generated narrative (populated by narration service, Phase 2)
    llm_narrative       TEXT,

    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Composite index — primary access pattern: (event_id, disaster_type)
CREATE INDEX IF NOT EXISTS idx_priority_results_event_disaster
    ON priority_results(event_id, disaster_type);

CREATE INDEX IF NOT EXISTS idx_priority_results_event_id
    ON priority_results(event_id);

CREATE INDEX IF NOT EXISTS idx_priority_results_priority_score
    ON priority_results(priority_score DESC);

CREATE INDEX IF NOT EXISTS idx_priority_results_zone_id
    ON priority_results(zone_id);

COMMENT ON TABLE priority_results IS
    'Priority scores for each affected zone per event. '
    'Composite score = weighted sum of population, infra, access, intensity.';

COMMENT ON COLUMN priority_results.scoring_weights IS
    'JSONB snapshot of priority_weights at computation time. '
    'Allows auditing if weights are changed between runs.';

COMMENT ON COLUMN priority_results.llm_narrative IS
    'LLM-generated plain-language narrative for this zone (Phase 2).';


-- ============================================================
-- VIEWS
-- ============================================================

-- Top-priority zones per event (useful for the priority panel)
CREATE OR REPLACE VIEW v_top_priority_zones AS
SELECT
    pr.event_id,
    pr.disaster_type,
    pr.priority_rank,
    pr.priority_score,
    pr.hospitals_affected,
    pr.road_segments_blocked,
    az.confidence,
    az.area_km2,
    az.intensity_metadata,
    az.geom,
    az.location_label,
    adm.name        AS district_name,
    adm.population  AS district_population
FROM priority_results pr
JOIN affected_zones   az  ON pr.zone_id      = az.zone_id
LEFT JOIN admin_zones adm ON pr.admin_zone_id = adm.zone_id
WHERE pr.priority_rank <= 10
ORDER BY pr.event_id, pr.priority_rank;

COMMENT ON VIEW v_top_priority_zones IS
    'Top 10 priority zones per event with joined geometry and admin data.';


-- Summary stats per event
CREATE OR REPLACE VIEW v_event_summary AS
SELECT
    de.event_id,
    de.disaster_type,
    de.display_name,
    de.date_start,
    de.status,
    COUNT(DISTINCT az.zone_id)                          AS total_zones,
    ROUND(SUM(az.area_km2)::NUMERIC, 2)                 AS total_area_km2,
    ROUND(AVG(az.confidence)::NUMERIC, 4)               AS avg_confidence,
    SUM(pr.hospitals_affected)                          AS total_hospitals_affected,
    MAX(pr.priority_score)                              AS max_priority_score
FROM disaster_events    de
LEFT JOIN affected_zones az  ON de.event_id = az.event_id
LEFT JOIN priority_results pr ON de.event_id = pr.event_id
GROUP BY de.event_id, de.disaster_type, de.display_name, de.date_start, de.status;

COMMENT ON VIEW v_event_summary IS
    'Per-event aggregate statistics for the dashboard header cards.';


-- ============================================================
-- SEED DATA — 5 Demo Events
-- ============================================================
-- Idempotent: uses INSERT ... ON CONFLICT DO NOTHING
-- Requires a unique constraint on (disaster_type, date_start, region)
-- ============================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_disaster_events_type_date_region'
    ) THEN
        ALTER TABLE disaster_events
            ADD CONSTRAINT uq_disaster_events_type_date_region
            UNIQUE (disaster_type, date_start, region);
    END IF;
END $$;

INSERT INTO disaster_events
    (disaster_type, display_name, region, state, date_start, date_end,
     status, data_source, thumbnail_color, description,
     bbox)
VALUES
(
    'flood', 'Kerala Floods 2018', 'Kerala', 'Kerala',
    '2018-08-01', '2018-08-31',
    'live', 'Sentinel-1 SAR + Attention U-Net', '#1e40af',
    'Catastrophic flooding following extreme monsoon rainfall across 14 Kerala districts.',
    ST_GeomFromText('POLYGON((76.0 9.5, 77.5 9.5, 77.5 11.0, 76.0 11.0, 76.0 9.5))', 4326)
),
(
    'wildfire', 'Uttarakhand Forest Fires 2024', 'Garhwal & Kumaon', 'Uttarakhand',
    '2024-04-15', '2024-05-10',
    'demo', 'Sentinel-2 SWIR NBR ratio (mock)', '#b91c1c',
    'Widespread forest fires across Uttarakhand oak and pine forests during the dry pre-monsoon season.',
    ST_GeomFromText('POLYGON((78.5 29.5, 80.5 29.5, 80.5 31.5, 78.5 31.5, 78.5 29.5))', 4326)
),
(
    'landslide', 'Himachal Pradesh Landslides 2023', 'Kullu & Mandi', 'Himachal Pradesh',
    '2023-07-12', '2023-08-05',
    'demo', 'Sentinel-1 SAR amplitude + SRTM slope (mock)', '#92400e',
    'Monsoon-triggered landslides blocking key highways in Kullu and Mandi districts.',
    ST_GeomFromText('POLYGON((76.5 31.0, 78.0 31.0, 78.0 32.5, 76.5 32.5, 76.5 31.0))', 4326)
),
(
    'cyclone', 'Cyclone Michaung 2023', 'Coastal Odisha', 'Odisha',
    '2023-12-04', '2023-12-06',
    'demo', 'INSAT-3D storm track + surge model (mock)', '#6d28d9',
    'Severe cyclonic storm Michaung making landfall on the Odisha/AP coast with 195 km/h winds.',
    ST_GeomFromText('POLYGON((84.0 19.0, 87.0 19.0, 87.0 21.5, 84.0 21.5, 84.0 19.0))', 4326)
),
(
    'earthquake', 'Gujarat Earthquake 2024', 'Kutch District', 'Gujarat',
    '2024-03-22', '2024-03-22',
    'demo', 'Sentinel-1 InSAR coherence (mock)', '#d97706',
    'Moderate magnitude earthquake in the Kutch seismic zone causing structural damage across several villages.',
    ST_GeomFromText('POLYGON((70.0 21.5, 72.5 21.5, 72.5 23.0, 70.0 23.0, 70.0 21.5))', 4326)
)
ON CONFLICT ON CONSTRAINT uq_disaster_events_type_date_region DO NOTHING;

-- Confirmation
DO $$
DECLARE n INTEGER;
BEGIN
    SELECT COUNT(*) INTO n FROM disaster_events;
    RAISE NOTICE 'disaster_events: % rows', n;
END $$;
