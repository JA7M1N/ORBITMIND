-- =============================================================================
-- OrbitalMind — Database Row Level Security (RLS) Configuration
-- =============================================================================
-- This script configures Row Level Security (RLS) for the PostGIS tables
-- to protect the data layer against unauthorized access, SQL injections,
-- and privilege escalation.
--
-- Setup:
--   psql -U postgres -d orbitalmind -f db/rls.sql
-- =============================================================================

-- ── 1. Enable RLS on all tables ──────────────────────────────────────────────
ALTER TABLE disaster_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE affected_zones  ENABLE ROW LEVEL SECURITY;
ALTER TABLE priority_results ENABLE ROW LEVEL SECURITY;
ALTER TABLE admin_zones      ENABLE ROW LEVEL SECURITY;

-- Force RLS even for table owners (optional, comment out if postgres user needs bypass)
-- ALTER TABLE disaster_events FORCE ROW LEVEL SECURITY;
-- ALTER TABLE affected_zones  FORCE ROW LEVEL SECURITY;
-- ALTER TABLE priority_results FORCE ROW LEVEL SECURITY;
-- ALTER TABLE admin_zones      FORCE ROW LEVEL SECURITY;


-- ── 2. Create Security Policies ──────────────────────────────────────────────

-- ── disaster_events Policies ──
DROP POLICY IF EXISTS select_public_disaster_events ON disaster_events;
CREATE POLICY select_public_disaster_events ON disaster_events
    FOR SELECT TO public USING (true);

DROP POLICY IF EXISTS modify_admin_disaster_events ON disaster_events;
CREATE POLICY modify_admin_disaster_events ON disaster_events
    FOR ALL TO postgres USING (true) WITH CHECK (true);


-- ── affected_zones Policies ──
DROP POLICY IF EXISTS select_public_affected_zones ON affected_zones;
CREATE POLICY select_public_affected_zones ON affected_zones
    FOR SELECT TO public USING (true);

DROP POLICY IF EXISTS modify_admin_affected_zones ON affected_zones;
CREATE POLICY modify_admin_affected_zones ON affected_zones
    FOR ALL TO postgres USING (true) WITH CHECK (true);


-- ── priority_results Policies ──
DROP POLICY IF EXISTS select_public_priority_results ON priority_results;
CREATE POLICY select_public_priority_results ON priority_results
    FOR SELECT TO public USING (true);

DROP POLICY IF EXISTS modify_admin_priority_results ON priority_results;
CREATE POLICY modify_admin_priority_results ON priority_results
    FOR ALL TO postgres USING (true) WITH CHECK (true);


-- ── admin_zones Policies ──
DROP POLICY IF EXISTS select_public_admin_zones ON admin_zones;
CREATE POLICY select_public_admin_zones ON admin_zones
    FOR SELECT TO public USING (true);

DROP POLICY IF EXISTS modify_admin_admin_zones ON admin_zones;
CREATE POLICY modify_admin_admin_zones ON admin_zones
    FOR ALL TO postgres USING (true) WITH CHECK (true);


-- ── 3. Verification Query ────────────────────────────────────────────────────
SELECT
    schemaname,
    tablename,
    rowsecurity as rls_enabled
FROM pg_tables
WHERE tablename IN ('disaster_events', 'affected_zones', 'priority_results', 'admin_zones');
