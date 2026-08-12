import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type * as maplibregl from 'maplibre-gl';
import { ToastContainer } from 'react-toastify';
import 'react-toastify/dist/ReactToastify.css';
import './App.css';

import DisasterNav from './components/DisasterNav';
import MapView from './components/MapView';
import AffectedZoneLayer from './components/AffectedZoneLayer';
import InfraMarkerLayer from './components/InfraMarkerLayer';
import RightPanel from './components/RightPanel';
import PlatformSummary from './components/PlatformSummary';
import ModuleComparison from './components/ModuleComparison';
import SatelliteTimeline from './components/SatelliteTimeline';

import {
  MOCK_MODULES,
  MOCK_EVENTS,
  MOCK_ZONES_BY_DISASTER,
  MOCK_FLOOD_INFRA,
  MOCK_NARRATIONS,
} from './mock/mockData';
import {
  getModules,
  getEvents,
  triggerAnalysis,
  getZones,
  DEMO_MODE,
} from './services/api';
import { TIMELINE_SNAPSHOTS } from './utils/moduleMeta';
import type { DisasterModule, DisasterEvent, DisasterType, PriorityZoneCollection } from './types';
import type { MapAction } from './types/copilot';

/**
 * State this app needs: which module/event is active, which zone is
 * selected, and per-module analysis progress. No Redux/Zustand — a
 * focused single-screen tool doesn't benefit from global store
 * ceremony at this scale.
 *
 * `activeType` vs `mapType`: these are deliberately two different
 * pieces of state, not one. `activeType` drives everything that must
 * change on frame 0 (the nav highlight, the data-disaster attribute
 * and therefore every accent color in the app). `mapType` drives
 * everything that should catch up 250ms later — the map's flyTo
 * target, which events/zones are shown, the right panel's content.
 * That gap is what makes the module switch read as a directed
 * sequence instead of one simultaneous flash. See switchDisaster().
 */
export default function App() {
  // ── Remote data (modules + events can be API-driven) ────────────────────────
  const [modules, setModules] = useState<DisasterModule[]>(MOCK_MODULES);
  const [allEvents, setAllEvents] = useState<DisasterEvent[]>(MOCK_EVENTS);
  const [zonesMap, setZonesMap] = useState<Record<string, PriorityZoneCollection>>(
    MOCK_ZONES_BY_DISASTER as unknown as Record<string, PriorityZoneCollection>,
  );

  // ── Disaster / module state ──────────────────────────────────────────────────
  const [activeType, setActiveType] = useState<DisasterType>('flood');
  const [mapType,    setMapType]    = useState<DisasterType>('flood');
  const [switching,  setSwitching]  = useState(false);
  const [selectedZoneId, setSelectedZoneId] = useState<string | null>('zone-idukki');
  const [map, setMap] = useState<maplibregl.Map | null>(null);
  const [snapshotIndex, setSnapshotIndex] = useState(4); // 4 = post-disaster peak
  const [compareOpen, setCompareOpen] = useState(false);

  // ── Mobile bottom-sheet state ────────────────────────────────────────────────
  const [sheetOpen, setSheetOpen] = useState(false);
  const isMobile = typeof window !== 'undefined' && window.innerWidth <= 768;

  // ── Analysis state ───────────────────────────────────────────────────────────
  const [revealedByType, setRevealedByType] = useState<Record<DisasterType, boolean>>({
    flood: true, wildfire: false, landslide: false, cyclone: false, earthquake: false,
  });
  const [analyzing, setAnalyzing] = useState(false);
  const [taskId,    setTaskId]    = useState<string | null>(null);

  const [showHospitals, setShowHospitals] = useState(true);
  const [showSchools,   setShowSchools]   = useState(true);

  // Welcome screen: one-time first-impression, disappears on first module selection.
  const [showWelcome, setShowWelcome] = useState(true);

  // ── Load real data on mount (falls back to mock if backend unavailable) ──────
  useEffect(() => {
    void (async () => {
      const [mods, evts] = await Promise.all([getModules(), getEvents()]);
      setModules(mods);
      setAllEvents(evts);
    })();
  }, []);

  // ── Derived data ─────────────────────────────────────────────────────────────
  const activeModule = useMemo(
    () => modules.find((m) => m.type === mapType) ?? modules[0],
    [modules, mapType],
  );

  const eventsForModule = useMemo(
    () => allEvents.filter((e) => e.disasterType === mapType),
    [allEvents, mapType],
  );

  const [selectedEventId, setSelectedEventId] = useState<string | null>(
    eventsForModule[0]?.eventId ?? null,
  );

  const activeEvent = useMemo(
    () => eventsForModule.find((e) => e.eventId === selectedEventId) ?? eventsForModule[0],
    [eventsForModule, selectedEventId],
  );

  const allZones: PriorityZoneCollection =
    (zonesMap[mapType] as PriorityZoneCollection | undefined) ??
    (MOCK_ZONES_BY_DISASTER[mapType] as PriorityZoneCollection);

  const zonesRevealed = revealedByType[mapType];

  // ── Theme: data-disaster drives all accent CSS variables in one write ────────
  useEffect(() => {
    document.documentElement.setAttribute('data-disaster', activeType);
    // Delayed title update — feels like a deliberate transition after module switch
    const mod = modules.find((m) => m.type === activeType);
    const t = setTimeout(() => {
      document.title = mod ? `OrbitalMind \u2014 ${mod.displayName}` : 'OrbitalMind';
    }, 300);
    return () => clearTimeout(t);
  }, [activeType, modules]);

  // ── Keyboard shortcuts ───────────────────────────────────────────────────────
  const reportButtonRef = useRef<HTMLButtonElement | null>(null);
  const navOpenRef      = useRef(false);

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      // Don't intercept if user is typing in an input
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;

      switch (e.key) {
        case 'Escape':
          // Deselect zone — map zooms back out, panel shows platform summary
          if (selectedZoneId) {
            setSelectedZoneId(null);
            setSheetOpen(false);
          } else if (!showWelcome) {
            setShowWelcome(true);
          }
          break;

        case 'r':
        case 'R':
          // Trigger report if event is loaded
          if (!showWelcome && zonesRevealed && reportButtonRef.current) {
            e.preventDefault();
            reportButtonRef.current.click();
          }
          break;

        case 'd':
        case 'D':
          // Toggle disaster nav open/closed on mobile
          navOpenRef.current = !navOpenRef.current;
          break;

        case 'ArrowDown':
          // Navigate priority list down
          if (!showWelcome && zonesRevealed) {
            e.preventDefault();
            const sortedZones = [...allZones.features].sort(
              (a, b) => a.properties.priorityRank - b.properties.priorityRank,
            );
            const idx = sortedZones.findIndex((f) => f.properties.zoneId === selectedZoneId);
            const next = sortedZones[Math.min(idx + 1, sortedZones.length - 1)];
            if (next) setSelectedZoneId(next.properties.zoneId);
          }
          break;

        case 'ArrowUp':
          // Navigate priority list up
          if (!showWelcome && zonesRevealed) {
            e.preventDefault();
            const sortedZones = [...allZones.features].sort(
              (a, b) => a.properties.priorityRank - b.properties.priorityRank,
            );
            const idx = sortedZones.findIndex((f) => f.properties.zoneId === selectedZoneId);
            const prev = sortedZones[Math.max(idx - 1, 0)];
            if (prev) setSelectedZoneId(prev.properties.zoneId);
          }
          break;
      }
    }
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [selectedZoneId, showWelcome, zonesRevealed, allZones]);

  // ── Module switching (the 20-second wow moment) ───────────────────────────────
  const revealedByTypeRef = useRef(revealedByType);
  revealedByTypeRef.current = revealedByType;
  const switchTimersRef = useRef<ReturnType<typeof setTimeout>[]>([]);

  /**
   * Orchestrated 4-step sequence:
   *   0ms    accent theme flips (data-disaster, via the effect above)
   *   150ms  zone layer + event list begin fading down
   *   250ms  map/events/panel content swaps → MapView's own effect
   *          picks up the new activeModule and starts its flyTo
   *   400ms  transition settles; revealed zones (if any) fade back in
   *   ~1700ms auto-run analysis for a module that's never been opened
   */
  const switchDisaster = useCallback(
    async (nextType: DisasterType) => {
      if (nextType === activeType) return;
      switchTimersRef.current.forEach(clearTimeout);
      switchTimersRef.current = [];

      setShowWelcome(false);
      setActiveType(nextType);
      setSwitching(true);
      setSelectedZoneId(null);
      setSnapshotIndex(4); // reset to post-disaster peak on disaster switch
      setSheetOpen(false);

      const t1 = setTimeout(async () => {
        setMapType(nextType);
        setTaskId(null);
        setAnalyzing(false);

        // Load events for the new module
        const nextEvts = await getEvents(nextType);
        const filtered = nextEvts.filter((e) => e.disasterType === nextType);
        setAllEvents((prev) => {
          const other = prev.filter((e) => e.disasterType !== nextType);
          return [...other, ...filtered];
        });
        setSelectedEventId(filtered[0]?.eventId ?? null);

        // Load zones for the new module if not already cached
        if (!revealedByTypeRef.current[nextType]) return;
        const firstEvt = filtered[0];
        if (!firstEvt) return;
        const zc = await getZones(firstEvt.eventId, nextType);
        setZonesMap((prev) => ({ ...prev, [nextType]: zc }));
      }, 250);
      switchTimersRef.current.push(t1);

      const t2 = setTimeout(() => setSwitching(false), 550);
      switchTimersRef.current.push(t2);

      const t3 = setTimeout(async () => {
        if (!revealedByTypeRef.current[nextType]) {
          const evts = allEvents.filter((e) => e.disasterType === nextType);
          const defaultEvt = evts[0];
          if (defaultEvt) {
            // Trigger real backend analysis (falls back to demo simulation)
            const result = await triggerAnalysis(defaultEvt.eventId, nextType);
            setTaskId(result.task_id);
            setAnalyzing(true);
          }
        }
      }, 1700);
      switchTimersRef.current.push(t3);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [activeType, allEvents],
  );

  useEffect(() => () => switchTimersRef.current.forEach(clearTimeout), []);

  function handleSelectModule(type: string) {
    // Always dismiss the welcome screen, even if the type is already active.
    // switchDisaster() guards against no-ops when type === activeType, so
    // we must explicitly close the welcome screen here first.
    setShowWelcome(false);
    void switchDisaster(type as DisasterType);
  }


  async function handleRunAnalysis() {
    if (!selectedEventId || analyzing || !activeEvent) return;
    setAnalyzing(true);
    const result = await triggerAnalysis(activeEvent.eventId, mapType);
    setTaskId(result.task_id);
  }

  async function handleAnalysisComplete() {
    setAnalyzing(false);
    setTaskId(null);
    setRevealedByType((prev) => ({ ...prev, [mapType]: true }));

    // Load real zones from backend after analysis completes
    if (activeEvent) {
      const zc = await getZones(activeEvent.eventId, mapType);
      setZonesMap((prev) => ({ ...prev, [mapType]: zc }));
    }

    // Auto-select top priority zone
    const topZone = [...allZones.features].sort(
      (a, b) => a.properties.priorityRank - b.properties.priorityRank,
    )[0];
    if (topZone) {
      setSelectedZoneId(topZone.properties.zoneId);
      if (isMobile) setSheetOpen(true);
    }
  }

  // Zone click: open bottom sheet on mobile
  function handleZoneSelect(zoneId: string) {
    setSelectedZoneId(zoneId);
    if (isMobile) setSheetOpen(true);
  }

  /**
   * handleMapCommand — called by CopilotChat when the LLM response
   * includes a MAP_ACTION tag. Drives the MapLibre map programmatically.
   *
   * ZOOM  → case-insensitive name match against loaded zones,
   *          then map.flyTo + setSelectedZoneId.
   * HIGHLIGHT → switches the active infra layer; the InfraMarkerLayer
   *             and AffectedZoneLayer read showHospitals/showSchools state.
   */
  function handleMapCommand(action: MapAction) {
    if (action.action === 'ZOOM' && action.target) {
      const needle = action.target.toLowerCase();
      const match  = allZones.features.find((f) =>
        f.properties.zoneName.toLowerCase().includes(needle),
      );
      if (match) {
        setSelectedZoneId(match.properties.zoneId);
        if (isMobile) setSheetOpen(true);
        // Fly the map to the matched zone's centroid (approximated from
        // the GeoJSON geometry bounding box or a hardcoded center point).
        // MapLibre flyTo is called via the `map` state ref.
        if (map) {
          // Compute the bounding-box centroid of the polygon so flyTo
          // lands at the geographic centre of the district, not an edge vertex.
          const geom = match.geometry as {
            type: string;
            coordinates: number[][][];
          };
          if (geom?.type === 'Polygon' && geom.coordinates?.[0]) {
            const ring = geom.coordinates[0];
            let sumLng = 0, sumLat = 0;
            for (const [lng, lat] of ring) { sumLng += lng; sumLat += lat; }
            const centLng = sumLng / ring.length;
            const centLat = sumLat / ring.length;
            map.flyTo({
              center:    [centLng, centLat] as [number, number],
              zoom:      10,
              duration:  1200,
              essential: true,
            });
          }
        }
      }
    }
    if (action.action === 'HIGHLIGHT' && action.layer) {
      // Toggle the relevant infra marker layer
      if (action.layer === 'hospitals') {
        setShowHospitals(true);
        setShowSchools(false);
      } else if (action.layer === 'roads' || action.layer === 'bridges') {
        // Roads and bridges are not separate toggle layers in the current
        // implementation — just ensure hospitals/schools don't occlude.
        setShowHospitals(false);
        setShowSchools(false);
      } else if (action.layer === 'schools') {
        setShowHospitals(false);
        setShowSchools(true);
      }
    }
  }

  const displayedZones = zonesRevealed
    ? allZones
    : { type: 'FeatureCollection' as const, features: [] };

  const snapshots = TIMELINE_SNAPSHOTS[mapType];
  const zoneOpacity = switching ? 0 : snapshots[snapshotIndex].opacity;

  // Custom map attribution text
  useEffect(() => {
    const el = document.querySelector('.maplibregl-ctrl-attrib-inner');
    if (el && !el.textContent?.includes('OrbitalMind')) {
      el.textContent = '© OpenStreetMap contributors | OrbitalMind Platform';
    }
  });

  return (
    <div className="app-shell">
      <DisasterNav
        modules={modules}
        activeType={activeType}
        onSelect={handleSelectModule}
        onCompareModules={() => setCompareOpen(true)}
      />

      <div className="app-shell__map-column">
        <MapView activeModule={activeModule} onReady={setMap} />
        {map && (
          <AffectedZoneLayer
            map={map}
            geojson={displayedZones}
            disasterType={mapType}
            selectedZoneId={selectedZoneId}
            onZoneClick={handleZoneSelect}
            opacityMultiplier={zoneOpacity}
          />
        )}
        {map && (
          <InfraMarkerLayer
            map={map}
            points={MOCK_FLOOD_INFRA}
            showHospitals={showHospitals}
            showSchools={showSchools}
            visible={mapType === 'flood' && zonesRevealed && !switching}
          />
        )}

        {mapType === 'flood' && zonesRevealed && (
          <div className="infra-toggle glass-panel" data-accent-transition>
            <button
              type="button"
              className={`infra-toggle__btn ${showHospitals ? 'infra-toggle__btn--active' : ''}`}
              onClick={() => setShowHospitals((v) => !v)}
            >
              Hospitals
            </button>
            <button
              type="button"
              className={`infra-toggle__btn ${showSchools ? 'infra-toggle__btn--active' : ''}`}
              onClick={() => setShowSchools((v) => !v)}
            >
              Schools
            </button>
          </div>
        )}

        {zonesRevealed && !switching && (
          <SatelliteTimeline
            disasterType={mapType}
            snapshotIndex={snapshotIndex}
            onChange={setSnapshotIndex}
          />
        )}
      </div>

      <div
        className={`app-shell__panel-column${sheetOpen ? ' app-shell__panel-column--open' : ''}`}
      >
        {/* Mobile drag handle */}
        <div
          className="bottom-sheet-handle"
          onClick={() => setSheetOpen((v) => !v)}
          role="button"
          aria-label={sheetOpen ? 'Close panel' : 'Open panel'}
          tabIndex={0}
          onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') setSheetOpen((v) => !v); }}
        />


        {!showWelcome && activeEvent && (
          <RightPanel
            module={activeModule}
            event={activeEvent}
            events={eventsForModule}
            selectedEventId={selectedEventId}
            onSelectEvent={setSelectedEventId}
            zones={allZones}
            zonesRevealed={zonesRevealed}
            selectedZoneId={selectedZoneId}
            onSelectZone={handleZoneSelect}
            narrations={MOCK_NARRATIONS}
            analyzing={analyzing}
            taskId={taskId}
            onRunAnalysis={() => void handleRunAnalysis()}
            onAnalysisComplete={() => void handleAnalysisComplete()}
            reportButtonRef={reportButtonRef}
            demoMode={DEMO_MODE}
            switching={switching}
            onMapCommand={handleMapCommand}
          />
        )}
      </div>

      {/* ── Full-screen welcome overlay (rendered above map + panel) ─────── */}
      {showWelcome && (
        <PlatformSummary modules={modules} onSelectModule={handleSelectModule} />
      )}

      <ModuleComparison
        open={compareOpen}
        onClose={() => setCompareOpen(false)}
        modules={modules}
        events={allEvents}
      />

      {/* Toast container — amber theme for backend fallback warnings */}
      <ToastContainer
        position="bottom-right"
        autoClose={4000}
        limit={2}
        theme="dark"
        style={{ zIndex: 'var(--z-toast)' } as React.CSSProperties}
      />
    </div>
  );
}
