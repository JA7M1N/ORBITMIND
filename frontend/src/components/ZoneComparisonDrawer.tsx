/**
 * ZoneComparisonDrawer
 * =====================
 * Side-by-side metric comparison for any two priority zones.
 *
 * This answers the most common operational question: "Should I deploy
 * resources to Zone A or Zone B?" Without this, the manager must mentally
 * hold two sets of numbers from two different cards while making a
 * decision under time pressure. This component makes that comparison
 * instantaneous and scannable.
 *
 * Design decisions:
 * - Grid layout (not flexbox columns) so the label column, A column, and
 *   B column are always perfectly aligned regardless of content length.
 * - The WORSE value in each row gets a subtle accent tint — not a red
 *   warning (wrong tone for a government tool) but a directional highlight.
 *   "Worse" is always the more urgent/critical value for that metric.
 * - Verdict banner at the bottom synthesises all metrics into one sentence.
 *   This is the only place "AI" language appears — and it's deterministic
 *   logic, not LLM output, so it's always correct.
 */

import { useEffect, useCallback } from 'react';
import type { PriorityZone, DisasterType } from '../types';
import {
  IconUsers,
  IconHospital,
  IconSchool,
  IconBridge,
  IconRoad,
} from './icons';
import './ZoneComparisonDrawer.css';

// ── Props ─────────────────────────────────────────────────────────────────────

interface ZoneComparisonDrawerProps {
  zoneA: PriorityZone;
  zoneB: PriorityZone | null;   // null → drawer is open but only one zone pinned
  disasterType: DisasterType;
  onClose: () => void;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmt(n: number): string {
  return n.toLocaleString('en-IN');
}

/**
 * Determines which zone is "worse" for a given metric.
 * "Worse" always means "more urgent" — higher pop, fewer roads, etc.
 * Returns 'A', 'B', or null (tied).
 */
function worse(
  valA: number,
  valB: number,
  direction: 'lower-is-worse' | 'higher-is-worse',
): 'A' | 'B' | null {
  if (valA === valB) return null;
  if (direction === 'lower-is-worse') {
    return valA < valB ? 'A' : 'B';
  }
  return valA > valB ? 'A' : 'B';
}

// ── Sub-components ─────────────────────────────────────────────────────────────

function CloseIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"
      aria-hidden="true">
      <path d="M18 6 6 18M6 6l12 12" />
    </svg>
  );
}

interface MetricRowProps {
  icon: React.ReactNode;
  label: string;
  valA: number;
  valB: number | null;
  format?: (v: number) => string;
  suffix?: string;
  /** Which direction indicates a worse situation */
  direction: 'lower-is-worse' | 'higher-is-worse';
  /** Override to show a score-bar in this row */
  showBar?: boolean;
}

function MetricRow({
  icon, label, valA, valB, format = fmt, suffix = '',
  direction, showBar,
}: MetricRowProps) {
  const worseZone = valB !== null ? worse(valA, valB, direction) : null;
  const displayA = `${format(valA)}${suffix}`;
  const displayB = valB !== null ? `${format(valB)}${suffix}` : '—';

  return (
    <div className="zone-cmp__row">
      <div className="zone-cmp__metric-label">
        <span className="zone-cmp__metric-icon">{icon}</span>
        {label}
      </div>

      <div className={`zone-cmp__cell${worseZone === 'A' ? ' zone-cmp__cell--worse' : ''}`}>
        {displayA}
        {showBar && (
          <div className="zone-cmp__score-bar">
            <div className="zone-cmp__score-bar-fill" style={{ width: `${valA * 100}%` }} />
          </div>
        )}
      </div>

      <div className={`zone-cmp__cell${worseZone === 'B' ? ' zone-cmp__cell--worse' : ''}`}>
        {displayB}
        {showBar && valB !== null && (
          <div className="zone-cmp__score-bar">
            <div className="zone-cmp__score-bar-fill" style={{ width: `${valB * 100}%` }} />
          </div>
        )}
      </div>
    </div>
  );
}

// ── Verdict logic ─────────────────────────────────────────────────────────────

function buildVerdict(a: PriorityZone, b: PriorityZone): { winner: string; reason: string } {
  // Simple weighted scoring: rank is the primary signal (lower = more urgent).
  // Ties broken by road accessibility (lower = harder to reach = more urgent).
  if (a.priorityRank < b.priorityRank) {
    return {
      winner: a.zoneName,
      reason: `ranked #${a.priorityRank} vs #${b.priorityRank} with ${a.roadsIntactPct}% road accessibility`,
    };
  }
  if (b.priorityRank < a.priorityRank) {
    return {
      winner: b.zoneName,
      reason: `ranked #${b.priorityRank} vs #${a.priorityRank} with ${b.roadsIntactPct}% road accessibility`,
    };
  }
  // Equal rank — defer to road accessibility (lower = worse)
  if (a.roadsIntactPct < b.roadsIntactPct) {
    return {
      winner: a.zoneName,
      reason: `equal rank but ${a.roadsIntactPct}% road accessibility vs ${b.roadsIntactPct}% — more isolated`,
    };
  }
  return {
    winner: b.zoneName,
    reason: `equal rank but ${b.roadsIntactPct}% road accessibility vs ${a.roadsIntactPct}% — more isolated`,
  };
}

// ── Main component ─────────────────────────────────────────────────────────────

export default function ZoneComparisonDrawer({
  zoneA,
  zoneB,
  disasterType: _disasterType,  // reserved for future disaster-specific metric labels
  onClose,
}: ZoneComparisonDrawerProps) {
  // Close on ESC
  const handleKey = useCallback(
    (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); },
    [onClose],
  );
  useEffect(() => {
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [handleKey]);

  const verdict = zoneB ? buildVerdict(zoneA, zoneB) : null;

  return (
    <>
      {/* Backdrop — only covers the map (left) side, not the drawer column */}
      <div
        className="zone-cmp-backdrop"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Drawer — fixed to the right edge, always fully visible */}
      <aside
        className="zone-cmp"
        role="dialog"
        aria-modal="true"
        aria-label="Zone comparison"
      >

        {/* ── Header ─────────────────────────────────────────────────────── */}
        <div className="zone-cmp__header">
          <span className="zone-cmp__title">Zone Comparison</span>
          <button
            type="button"
            className="zone-cmp__close"
            onClick={onClose}
            aria-label="Close comparison"
          >
            <CloseIcon />
          </button>
        </div>

        {/* ── Zone name headers ───────────────────────────────────────────── */}
        <div className="zone-cmp__zone-headers">
          {/* Empty label cell */}
          <div style={{ padding: 'var(--space-3) var(--space-4)' }} />

          {/* Zone A */}
          <div className="zone-cmp__zone-label">
            <span className="zone-cmp__zone-name">{zoneA.zoneName}</span>
            <span className="zone-cmp__zone-rank">
              Rank #{zoneA.priorityRank} · {(zoneA.priorityScore * 100).toFixed(0)}%
            </span>
          </div>

          {/* Zone B */}
          {zoneB ? (
            <div className="zone-cmp__zone-label">
              <span className="zone-cmp__zone-name">{zoneB.zoneName}</span>
              <span className="zone-cmp__zone-rank">
                Rank #{zoneB.priorityRank} · {(zoneB.priorityScore * 100).toFixed(0)}%
              </span>
            </div>
          ) : (
            <div className="zone-cmp__zone-label" style={{ justifyContent: 'center', alignItems: 'center' }}>
              <span style={{ fontSize: 11, color: 'var(--text-tertiary)', fontStyle: 'italic' }}>
                Click + on a second zone
              </span>
            </div>
          )}
        </div>

        {/* ── Metric rows ─────────────────────────────────────────────────── */}
        <div className="zone-cmp__body">

          <div className="zone-cmp__section-header">
            <div className="zone-cmp__section-title">Priority</div>
          </div>

          <MetricRow
            icon={<span style={{ fontSize: 11 }}>⬆</span>}
            label="Score"
            valA={zoneA.priorityScore}
            valB={zoneB?.priorityScore ?? null}
            format={(v) => (v * 100).toFixed(0)}
            suffix="%"
            direction="higher-is-worse"
            showBar
          />

          <MetricRow
            icon={<span style={{ fontSize: 11 }}>#</span>}
            label="Rank"
            valA={zoneA.priorityRank}
            valB={zoneB?.priorityRank ?? null}
            format={(v) => String(v)}
            direction="lower-is-worse"
          />

          <div className="zone-cmp__section-header">
            <div className="zone-cmp__section-title">People & Infrastructure</div>
          </div>

          <MetricRow
            icon={<IconUsers size={12} />}
            label="Population"
            valA={zoneA.populationAffected}
            valB={zoneB?.populationAffected ?? null}
            direction="higher-is-worse"
          />

          <MetricRow
            icon={<IconHospital size={12} />}
            label="Hospitals"
            valA={zoneA.hospitalsAffected}
            valB={zoneB?.hospitalsAffected ?? null}
            format={(v) => String(v)}
            direction="higher-is-worse"
          />

          <MetricRow
            icon={<IconSchool size={12} />}
            label="Schools"
            valA={zoneA.schoolsAffected}
            valB={zoneB?.schoolsAffected ?? null}
            format={(v) => String(v)}
            direction="higher-is-worse"
          />

          <MetricRow
            icon={<IconBridge size={12} />}
            label="Bridges"
            valA={zoneA.bridgesAtRisk}
            valB={zoneB?.bridgesAtRisk ?? null}
            format={(v) => String(v)}
            direction="higher-is-worse"
          />

          <div className="zone-cmp__section-header">
            <div className="zone-cmp__section-title">Logistics</div>
          </div>

          <MetricRow
            icon={<IconRoad size={12} />}
            label="Road access"
            valA={zoneA.roadsIntactPct}
            valB={zoneB?.roadsIntactPct ?? null}
            format={(v) => String(v)}
            suffix="%"
            direction="lower-is-worse"
          />

          <MetricRow
            icon={<span style={{ fontSize: 11 }}>✓</span>}
            label="Confidence"
            valA={zoneA.confidence}
            valB={zoneB?.confidence ?? null}
            format={(v) => (v * 100).toFixed(0)}
            suffix="%"
            direction="lower-is-worse"
          />
        </div>

        {/* ── Verdict banner ───────────────────────────────────────────────── */}
        {verdict && (
          <div className="zone-cmp__verdict">
            <div className="zone-cmp__verdict-label">Recommended priority</div>
            <div className="zone-cmp__verdict-text">
              Deploy to{' '}
              <span className="zone-cmp__verdict-highlight">{verdict.winner}</span>
              {' '}first — {verdict.reason}.
            </div>
          </div>
        )}
      </aside>
    </>
  );
}
