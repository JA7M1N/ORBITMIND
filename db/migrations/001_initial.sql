-- ============================================================
-- OrbitalMind — Migration 001: Initial Schema
-- ============================================================
-- Idempotent: safe to run multiple times.
-- Run against a fresh database:
--   psql -U postgres -d orbitalmind -f db/migrations/001_initial.sql
--
-- Pre-conditions:
--   CREATE DATABASE orbitalmind;
-- ============================================================

BEGIN;

-- ── Extensions ────────────────────────────────────────────────

-- PostGIS: spatial types and functions (requires OS-level install via StackBuilder)
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_topology;

-- UUID generation without calling gen_random_uuid() (PG < 13 compat)
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Fuzzy text search (used for event slug resolution)
CREATE EXTENSION IF NOT EXISTS pg_trgm;


-- ── Table: disaster_events ────────────────────────────────────

CREATE TABLE IF NOT EXISTS disaster_events (
    event_id        UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    disaster_type   VARCHAR(30)   NOT NULL,
    display_name    VARCHAR(200)  NOT NULL,
    region          VARCHAR(200),
    state           VARCHAR(100),
    date_start      DATE,
    date_end        DATE,
    status          VARCHAR(20)   NOT NULL DEFAULT 'live',
    data_source     VARCHAR(200),
    thumbnail_color VARCHAR(10),
    description     TEXT,
    -- Full PostGIS geometry column (bounding polygon, SRID 4326)
    bbox            GEOMETRY(POLYGON, 4326),
    -- Text fallback for pre-PostGIS setups
    bbox_text       TEXT,
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

-- Unique event per type + start date + region (enables idempotent seeding)
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

CREATE INDEX IF NOT EXISTS idx_de_type ON disaster_events(disaster_type);
CREATE INDEX IF NOT EXISTS idx_de_date ON disaster_events(date_start);


-- ── Table: affected_zones ─────────────────────────────────────

CREATE TABLE IF NOT EXISTS affected_zones (
    zone_id             UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id            UUID          REFERENCES disaster_events(event_id) ON DELETE CASCADE,
    disaster_type       VARCHAR(30),
    -- PostGIS geometry (Polygon / MultiPolygon, WGS-84)
    geom                GEOMETRY(GEOMETRY, 4326),
    -- GeoJSON geometry string (text fallback when PostGIS not yet active)
    geom_text           TEXT,
    confidence          FLOAT         CHECK (confidence BETWEEN 0.0 AND 1.0),
    area_km2            FLOAT         CHECK (area_km2 >= 0),
    -- Disaster-specific intensity fields (SWIR indices, SAR backscatter, etc.)
    intensity_metadata  JSONB         NOT NULL DEFAULT '{}',
    source              VARCHAR(50)   NOT NULL DEFAULT 'demo',
    created_at          TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_az_event    ON affected_zones(event_id);
CREATE INDEX IF NOT EXISTS idx_az_type     ON affected_zones(disaster_type);
CREATE INDEX IF NOT EXISTS idx_az_conf     ON affected_zones(confidence);

-- PostGIS spatial index (active once PostGIS is installed)
CREATE INDEX IF NOT EXISTS idx_az_geom     ON affected_zones USING GIST(geom);


-- ── Table: admin_zones ────────────────────────────────────────

CREATE TABLE IF NOT EXISTS admin_zones (
    zone_id     UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    name        VARCHAR(200),
    district    VARCHAR(200),
    state       VARCHAR(100),
    taluk       VARCHAR(200),
    population  BIGINT        CHECK (population >= 0),
    area_km2    FLOAT         CHECK (area_km2 > 0),
    -- District boundary polygon (MultiPolygon, WGS-84)
    geom        GEOMETRY(MULTIPOLYGON, 4326),
    -- Text fallback
    geom_text   TEXT,
    created_at  TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_adm_state   ON admin_zones(state);
CREATE INDEX IF NOT EXISTS idx_adm_name    ON admin_zones(name);
CREATE INDEX IF NOT EXISTS idx_adm_geom    ON admin_zones USING GIST(geom);


-- ── Table: priority_results ───────────────────────────────────

CREATE TABLE IF NOT EXISTS priority_results (
    result_id           UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id            UUID          REFERENCES disaster_events(event_id) ON DELETE CASCADE,
    admin_zone_id       UUID          REFERENCES admin_zones(zone_id),
    disaster_type       VARCHAR(30),
    zone_name           VARCHAR(200),
    priority_rank       INTEGER       CHECK (priority_rank >= 1),
    priority_score      FLOAT         CHECK (priority_score BETWEEN 0.0 AND 1.0),
    -- Component scores (for transparency / audit)
    population_score    FLOAT,
    infra_score         FLOAT,
    access_score        FLOAT,
    intensity_score     FLOAT,
    -- Infrastructure impact counts (from OSM overlay)
    hospitals_affected  INTEGER       NOT NULL DEFAULT 0,
    schools_affected    INTEGER       NOT NULL DEFAULT 0,
    bridges_affected    INTEGER       NOT NULL DEFAULT 0,
    -- Snapshot of the scoring weights used in this run
    scoring_weights     JSONB,
    created_at          TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pr_event  ON priority_results(event_id);
CREATE INDEX IF NOT EXISTS idx_pr_type   ON priority_results(disaster_type);
CREATE INDEX IF NOT EXISTS idx_pr_rank   ON priority_results(event_id, priority_rank);


-- ── Useful views ──────────────────────────────────────────────

CREATE OR REPLACE VIEW v_top_priority_zones AS
SELECT DISTINCT ON (pr.event_id)
    de.display_name    AS event_name,
    de.disaster_type,
    pr.zone_name       AS top_zone,
    pr.priority_score,
    pr.hospitals_affected,
    adm.population,
    pr.created_at
FROM priority_results pr
JOIN disaster_events de  ON pr.event_id      = de.event_id
LEFT JOIN admin_zones adm ON pr.admin_zone_id = adm.zone_id
WHERE pr.priority_rank = 1
ORDER BY pr.event_id, pr.priority_score DESC;

COMMENT ON VIEW v_top_priority_zones IS
    'One row per event — the single highest-priority zone.';


CREATE OR REPLACE VIEW v_event_summary AS
SELECT
    de.event_id,
    de.disaster_type,
    de.display_name,
    de.date_start,
    de.status,
    COUNT(DISTINCT az.zone_id)      AS zone_count,
    ROUND(AVG(az.confidence)::NUMERIC, 4) AS avg_confidence,
    ROUND(SUM(az.area_km2)::NUMERIC, 2)   AS total_area_km2,
    COUNT(DISTINCT pr.result_id)    AS priority_count,
    MAX(pr.priority_score)          AS max_priority_score
FROM disaster_events de
LEFT JOIN affected_zones az   ON de.event_id = az.event_id
LEFT JOIN priority_results pr ON de.event_id = pr.event_id
GROUP BY de.event_id, de.disaster_type, de.display_name, de.date_start, de.status;

COMMENT ON VIEW v_event_summary IS
    'Per-event aggregate statistics for dashboard header cards.';


COMMIT;

-- ── Post-migration instructions ───────────────────────────────
-- After running this migration:
--
-- 1. Import OSM data (requires osm2pgsql):
--    osm2pgsql -d orbitalmind -H localhost -U postgres --create --slim kerala-latest.osm.pbf
--
-- 2. Install scoring function:
--    psql -U postgres -d orbitalmind -f db/priority_scoring.sql
--
-- 3. Seed demo events and zones:
--    python scripts/setup_schema.py --password postgres
--
-- 4. Validate:
--    python scripts/validate_kerala_demo.py
-- ============================================================
