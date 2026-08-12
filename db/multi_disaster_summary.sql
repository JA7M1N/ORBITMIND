-- ============================================================
-- OrbitalMind — Multi-Disaster Platform Summary
-- ============================================================
-- Aggregate statistics across all 5 disaster modules.
-- Intended for:
--   1. The FastAPI /api/platform/summary endpoint
--   2. The dashboard header metrics
--   3. Judge presentation: "how many people covered?"
--
-- Run:
--   psql -U postgres -d orbitalmind -f db/multi_disaster_summary.sql
--
-- Note:
--   population_affected comes from admin_zones (2011 census)
--   joined via priority_results.admin_zone_id.
--   If OSM data not loaded, hospitals/schools will be 0.
--   If priority_results is empty, run load_all_demo_events.py first.
-- ============================================================

\echo ''
\echo '============================================================'
\echo '  OrbitalMind — Multi-Disaster Platform Summary'
\echo '============================================================'
\echo ''

-- ── 1. Full summary by disaster type ─────────────────────────

SELECT
    pr.disaster_type                                    AS "Disaster",
    COUNT(DISTINCT pr.event_id)::INTEGER                AS "Events",
    COUNT(DISTINCT pr.result_id)::INTEGER               AS "Districts Scored",
    TO_CHAR(COALESCE(SUM(adm.population), 0), 'FM99,999,999')
                                                        AS "Population at Risk",
    COALESCE(SUM(pr.hospitals_affected), 0)::INTEGER    AS "Hospitals",
    COALESCE(SUM(pr.schools_affected),   0)::INTEGER    AS "Schools",
    COALESCE(SUM(pr.bridges_affected),   0)::INTEGER    AS "Bridges",
    ROUND(AVG(pr.priority_score)::NUMERIC, 4)           AS "Avg Priority Score",
    ROUND(MAX(pr.priority_score)::NUMERIC, 4)           AS "Max Priority Score"
FROM priority_results pr
LEFT JOIN admin_zones adm ON pr.admin_zone_id = adm.zone_id
GROUP BY pr.disaster_type
ORDER BY SUM(adm.population) DESC NULLS LAST;

\echo ''

-- ── 2. Top priority zone per disaster ─────────────────────────

\echo '--- Top Zone per Disaster Module ---'
\echo ''

SELECT
    pr.disaster_type                                AS "Module",
    adm.name                                        AS "Top District",
    ROUND(pr.priority_score::NUMERIC, 4)            AS "Priority Score",
    pr.priority_rank                                AS "Rank",
    pr.hospitals_affected                           AS "Hospitals",
    TO_CHAR(COALESCE(adm.population, 0), 'FM99,999,999') AS "Population",
    de.display_name                                 AS "Event Name"
FROM priority_results pr
JOIN admin_zones adm    ON pr.admin_zone_id = adm.zone_id
JOIN disaster_events de ON pr.event_id      = de.event_id
WHERE pr.priority_rank = 1
ORDER BY pr.priority_score DESC;

\echo ''

-- ── 3. Platform totals (single row) ───────────────────────────

\echo '--- Platform-Wide Totals ---'
\echo ''

SELECT
    COUNT(DISTINCT pr.event_id)::INTEGER                    AS "Total Events",
    COUNT(DISTINCT pr.result_id)::INTEGER                   AS "Total Districts Scored",
    TO_CHAR(COALESCE(SUM(adm.population), 0), 'FM999,999,999')
                                                            AS "Total Population Covered",
    COALESCE(SUM(pr.hospitals_affected), 0)::INTEGER        AS "Total Hospitals at Risk",
    COALESCE(SUM(pr.schools_affected),   0)::INTEGER        AS "Total Schools at Risk",
    5                                                       AS "Active Modules",
    ROUND(AVG(pr.priority_score)::NUMERIC, 4)               AS "Platform Avg Score"
FROM priority_results pr
LEFT JOIN admin_zones adm ON pr.admin_zone_id = adm.zone_id;

\echo ''

-- ── 4. Event timeline ─────────────────────────────────────────

\echo '--- Event Timeline ---'
\echo ''

SELECT
    disaster_type   AS "Module",
    display_name    AS "Event",
    date_start      AS "Start Date",
    date_end        AS "End Date",
    status          AS "Status",
    data_source     AS "Satellite Source"
FROM disaster_events
ORDER BY date_start;

\echo ''
\echo '============================================================'
\echo '  Run python scripts/load_all_demo_events.py to populate.'
\echo '============================================================'
\echo ''
