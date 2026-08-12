import { useRef, useState, type RefObject } from 'react';
import type {
  DisasterEvent,
  DisasterModule,
  NarrationResponse,
  PriorityZoneCollection,
} from '../types';
import type { MapAction } from '../types/copilot';
import EventSelector from './EventSelector';
import AnalysisProgress from './AnalysisProgress';
import StatsSummary from './StatsSummary';
import PriorityList from './PriorityList';
import NarrationPanel from './NarrationPanel';
import GenerateReportButton from './GenerateReportButton';
import CopilotChat from './CopilotChat';
import ZoneComparisonDrawer from './ZoneComparisonDrawer';
import './RightPanel.css';

// ── Tab types ─────────────────────────────────────────────────────────────────

type RightTab = 'analysis' | 'copilot';

// ── Icons ─────────────────────────────────────────────────────────────────────

function AnalysisTabIcon() {
  return (
    <svg
      className="right-panel__tab-icon"
      width="13"
      height="13"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
    </svg>
  );
}

function CopilotTabIcon() {
  return (
    <svg
      className="right-panel__tab-icon"
      width="13"
      height="13"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
      <circle cx="9"  cy="10" r="1" fill="currentColor" />
      <circle cx="12" cy="10" r="1" fill="currentColor" />
      <circle cx="15" cy="10" r="1" fill="currentColor" />
    </svg>
  );
}

// ── Props ─────────────────────────────────────────────────────────────────────

interface RightPanelProps {
  module: DisasterModule;
  event: DisasterEvent;
  events: DisasterEvent[];
  selectedEventId: string | null;
  onSelectEvent: (eventId: string) => void;
  zones: PriorityZoneCollection;
  zonesRevealed: boolean;
  selectedZoneId: string | null;
  onSelectZone: (zoneId: string) => void;
  narrations: Record<string, NarrationResponse>;
  analyzing: boolean;
  taskId: string | null;
  onRunAnalysis: () => void;
  onAnalysisComplete: () => void;
  /** Ref threaded from App so keyboard shortcut R can trigger report download. */
  reportButtonRef?: RefObject<HTMLButtonElement | null>;
  /** Forwarded from api.ts — controls AnalysisProgress demo vs real WS. */
  demoMode?: boolean;
  /** When true the panel is mid-switch — CSS fades content out then back in. */
  switching?: boolean;
  /** Called when the copilot emits a map control command. */
  onMapCommand?: (action: MapAction) => void;
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function RightPanel({
  module,
  event,
  events,
  selectedEventId,
  onSelectEvent,
  zones,
  zonesRevealed,
  selectedZoneId,
  onSelectZone,
  narrations,
  analyzing,
  taskId,
  onRunAnalysis,
  onAnalysisComplete,
  reportButtonRef,
  demoMode = true,
  switching = false,
  onMapCommand,
}: RightPanelProps) {
  const listRef = useRef<HTMLDivElement>(null);
  const [activeTab, setActiveTab] = useState<RightTab>('analysis');

  // ── Comparison state ────────────────────────────────────────────────────────
  // Max 2 zone IDs can be pinned. When 2 are pinned the drawer opens.
  // Clicking an already-pinned zone's button removes it.
  const [comparedZoneIds, setComparedZoneIds] = useState<string[]>([]);
  const [compareOpen, setCompareOpen] = useState(false);

  function handleCompareToggle(zoneId: string) {
    setComparedZoneIds((prev) => {
      if (prev.includes(zoneId)) {
        // Remove — always close the drawer when de-selecting
        const next = prev.filter((id) => id !== zoneId);
        setCompareOpen(false);
        return next;
      }
      const next = [...prev, zoneId].slice(-2); // keep max 2, newest last
      // Only open the drawer when the SECOND zone is pinned
      if (next.length === 2) setCompareOpen(true);
      return next;
    });
  }

  // Clear comparisons when disaster module changes
  // (handled via key reset at the App level, so zones change anyway)
  // But also reset if zones become empty again (analysis reset).
  if (!zonesRevealed && comparedZoneIds.length > 0) {
    setComparedZoneIds([]);
    setCompareOpen(false);
  }

  const sortedZones = zonesRevealed
    ? [...zones.features].sort((a, b) => a.properties.priorityRank - b.properties.priorityRank)
    : [];
  const revealedZoneProps = sortedZones.map((f) => f.properties);

  const selected = zonesRevealed
    ? zones.features.find((f) => f.properties.zoneId === selectedZoneId)?.properties
    : undefined;

  const totalPopulationAffected = revealedZoneProps.reduce((s, z) => s + z.populationAffected, 0);
  const criticalZoneCount       = revealedZoneProps.filter((z) => z.priorityScore >= 0.75).length;
  const averageConfidence       = revealedZoneProps.length
    ? revealedZoneProps.reduce((s, z) => s + z.confidence, 0) / revealedZoneProps.length
    : 0;

  const reportData = zonesRevealed
    ? { module, event, zones: revealedZoneProps, narrations, totalPopulationAffected, criticalZoneCount, averageConfidence }
    : null;

  // Derive the zone name for the active zone (passed to CopilotChat)
  const activeZoneName = selected?.zoneName ?? selectedZoneId;

  // Fallback no-op if parent doesn't wire up onMapCommand
  const handleMapCommand = onMapCommand ?? (() => undefined);

  return (
    <aside
      className="right-panel glass-panel"
      data-active="true"
      data-accent-transition
      data-switching={switching ? 'true' : undefined}
    >

      {/* ── Panel Header (always visible) ─────────────────────────────────── */}
      <div className="right-panel__header">
        <span className="eyebrow">{module.displayName} · {module.regionLabel}</span>
        <div className="right-panel__event-name">{event.name}</div>
        <div className="right-panel__summary-row">
          <StatsSummary zones={revealedZoneProps} disasterType={module.type} eventData={event} />
        </div>
      </div>

      {/* ── Tab Bar ────────────────────────────────────────────────────────── */}
      <div className="right-panel__tabs" role="tablist" aria-label="Right panel tabs">
        <button
          type="button"
          role="tab"
          id="tab-analysis"
          aria-selected={activeTab === 'analysis'}
          aria-controls="tabpanel-analysis"
          className={`right-panel__tab${activeTab === 'analysis' ? ' right-panel__tab--active' : ''}`}
          onClick={() => setActiveTab('analysis')}
        >
          <AnalysisTabIcon />
          Priority Analysis
        </button>
        <button
          type="button"
          role="tab"
          id="tab-copilot"
          aria-selected={activeTab === 'copilot'}
          aria-controls="tabpanel-copilot"
          className={`right-panel__tab${activeTab === 'copilot' ? ' right-panel__tab--active' : ''}`}
          onClick={() => setActiveTab('copilot')}
        >
          <CopilotTabIcon />
          AI Copilot
        </button>
      </div>

      {/* Compare-mode hint: shown only when exactly 1 zone is pinned */}
      {comparedZoneIds.length === 1 && (() => {
        const pinnedZone = zones.features.find(
          (f) => f.properties.zoneId === comparedZoneIds[0],
        )?.properties;
        return (
          <div className="right-panel__compare-hint">
            <span className="right-panel__compare-hint-icon">⊕</span>
            <span className="right-panel__compare-hint-text">
              <strong>{pinnedZone?.zoneName ?? 'Zone'}</strong> pinned — hover another card and click <kbd>+</kbd>
            </span>
            <button
              type="button"
              className="right-panel__compare-hint-close"
              onClick={() => setComparedZoneIds([])}
              aria-label="Cancel comparison"
            >×</button>
          </div>
        );
      })()}

      {/* ── Tab: Priority Analysis ─────────────────────────────────────────── */}
      {activeTab === 'analysis' && (
        <div
          id="tabpanel-analysis"
          role="tabpanel"
          aria-labelledby="tab-analysis"
          className="right-panel__body"
        >
          <EventSelector
            events={events}
            regionLabel={module.regionLabel}
            moduleStatus={module.status}
            selectedEventId={selectedEventId}
            onSelectEvent={onSelectEvent}
            onRunAnalysis={onRunAnalysis}
            analyzing={analyzing}
            completed={zonesRevealed}
          />

          {taskId && (
            <div style={{ marginTop: 'var(--space-3)' }}>
              <AnalysisProgress
                taskId={taskId}
                onComplete={onAnalysisComplete}
                forceDemoMode={demoMode}
              />
            </div>
          )}

          <span className="eyebrow" style={{ marginTop: 'var(--space-4)', display: 'block' }}>
            Priority ranking
          </span>

          {/* Skeleton: shown while analysis is running (before zones are revealed) */}
          {analyzing && !zonesRevealed && (
            <div className="priority-skeleton" style={{ marginTop: 'var(--space-3)' }}>
              {Array.from({ length: 5 }).map((_, i) => (
                <div key={i} className="priority-skeleton__card" />
              ))}
            </div>
          )}

          {/* Empty hint: not analyzing, no zones yet */}
          {!zonesRevealed && !analyzing && (
            <p className="right-panel__empty-hint">
              Run analysis on the selected event to score priority zones.
            </p>
          )}

          {/* Real priority cards: staggered fade-in after skeleton */}
          <div ref={listRef} style={{ marginTop: 'var(--space-3)' }}>
            <PriorityList
              zones={revealedZoneProps}
              disasterType={module.type}
              selectedZoneId={selectedZoneId}
              onZoneSelect={onSelectZone}
              comparedZoneIds={comparedZoneIds}
              onCompareToggle={zonesRevealed ? handleCompareToggle : undefined}
            />
          </div>

          {selected && (
            <NarrationPanel
              eventId={event.eventId}
              zone={selected}
              disasterType={module.type}
              narrations={narrations}
            />
          )}

          <GenerateReportButton data={reportData} buttonRef={reportButtonRef} />
        </div>
      )}

      {/* ── Tab: AI Copilot ───────────────────────────────────────────────── */}
      {activeTab === 'copilot' && (
        <div
          id="tabpanel-copilot"
          role="tabpanel"
          aria-labelledby="tab-copilot"
          className="right-panel__copilot-body"
        >
          <CopilotChat
            eventId={selectedEventId}
            disasterType={module.type}
            activeZoneId={activeZoneName ?? null}
            onMapCommand={handleMapCommand}
          />
        </div>
      )}

      {/* ── Zone Comparison Drawer ────────────────────────────────────────── */}
      {compareOpen && comparedZoneIds.length >= 2 && (() => {
        const zoneA = zones.features.find(
          (f) => f.properties.zoneId === comparedZoneIds[0],
        )?.properties;
        const zoneB = zones.features.find(
          (f) => f.properties.zoneId === comparedZoneIds[1],
        )?.properties ?? null;
        if (!zoneA) return null;
        return (
          <ZoneComparisonDrawer
            zoneA={zoneA}
            zoneB={zoneB}
            disasterType={module.type}
            onClose={() => { setCompareOpen(false); setComparedZoneIds([]); }}
          />
        );
      })()}
    </aside>
  );
}
