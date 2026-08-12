import type { DisasterType, PriorityZone } from '../types';
import { IconUsers, IconHospital, IconSchool, IconBridge, IconRoad } from './icons';
import './PriorityCard.css';

interface PriorityCardProps {
  zone: PriorityZone;
  disasterType: DisasterType;
  rank: number;
  isSelected: boolean;
  onSelect: () => void;
  /** Called when user pins this zone for comparison. */
  onCompare?: () => void;
  /** Whether this zone is currently pinned in the comparison drawer. */
  isCompared?: boolean;
}

function formatNumber(n: number): string {
  return n.toLocaleString('en-IN');
}

/** Rank 1 → solid accent. 2/3 step down in accent opacity. 4+ → neutral.
 * The gradient itself communicates "how urgent," so nothing else on the
 * badge needs to — no numbers-as-color-scale, no extra iconography. */
function rankBadgeClass(rank: number): string {
  if (rank === 1) return 'priority-rank--1';
  if (rank === 2) return 'priority-rank--2';
  if (rank === 3) return 'priority-rank--3';
  return 'priority-rank--other';
}

function confidenceTier(confidence: number): 'high' | 'medium' | 'low' {
  if (confidence > 0.8) return 'high';
  if (confidence >= 0.6) return 'medium';
  return 'low';
}

export default function PriorityCard({
  zone,
  rank,
  isSelected,
  onSelect,
  onCompare,
  isCompared = false,
}: PriorityCardProps) {
  const tier = confidenceTier(zone.confidence);

  return (
    <div
      role="button"
      tabIndex={0}
      className={`priority-card ${isSelected ? 'priority-card--selected' : ''}`}
      onClick={onSelect}
      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelect(); } }}
      aria-pressed={isSelected}
      data-zone-id={zone.zoneId}
      data-accent-transition
    >
      <span className={`priority-rank ${rankBadgeClass(rank)} font-mono`}>{rank}</span>

      <span className="priority-card__body">
        <span className="priority-card__name-row">
          <span className="priority-card__name">{zone.zoneName}</span>
          <span className="priority-card__name-right">
            <span className="priority-card__score font-mono">
              {(zone.priorityScore * 100).toFixed(0)}%
            </span>
            {onCompare && (
              <button
                type="button"
                className={`priority-card__compare-btn${isCompared ? ' priority-card__compare-btn--active' : ''}`}
                onClick={(e) => { e.stopPropagation(); onCompare(); }}
                title={isCompared ? 'Remove from comparison' : 'Compare this zone'}
                aria-label={isCompared ? 'Remove from comparison' : 'Compare this zone'}
                aria-pressed={isCompared}
              >
                {isCompared ? '−' : '+'}
              </button>
            )}
          </span>
        </span>

        <span className="priority-card__score-bar">
          <span
            className="priority-card__score-bar-fill"
            style={{ width: `${zone.priorityScore * 100}%` }}
          />
        </span>

        <span className="priority-card__footer">
          <span className="priority-card__stats">
            <span className="priority-card__stat" title="Population affected">
              <IconUsers />
              <span className="font-mono">{formatNumber(zone.populationAffected)}</span>
            </span>
            <span className="priority-card__stat" title="Hospitals affected">
              <IconHospital />
              <span className="font-mono">{zone.hospitalsAffected}</span>
            </span>
            <span className="priority-card__stat" title="Schools affected">
              <IconSchool />
              <span className="font-mono">{zone.schoolsAffected}</span>
            </span>
            <span className="priority-card__stat" title="Bridges at risk">
              <IconBridge />
              <span className="font-mono">{zone.bridgesAtRisk}</span>
            </span>
            <span className="priority-card__stat" title="Roads intact">
              <IconRoad />
              <span className="font-mono">{zone.roadsIntactPct}%</span>
            </span>
          </span>

          <span className={`confidence-pill confidence-pill--${tier}`}>
            {(zone.confidence * 100).toFixed(0)}%
          </span>
        </span>
      </span>
    </div>
  );
}
