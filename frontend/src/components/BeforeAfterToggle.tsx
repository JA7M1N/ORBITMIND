import './BeforeAfterToggle.css';

export type DisasterPhase = 'pre' | 'post';

interface BeforeAfterToggleProps {
  phase: DisasterPhase;
  onChange: (phase: DisasterPhase) => void;
  preDate: string;
  postDate: string;
}

/**
 * Bottom-left, deliberately small and quiet — this toggle is a
 * secondary lens on the map, not a control panel. It should register
 * as "oh, I can rewind this" without ever pulling focus away from the
 * zone data itself, so it gets one visual language (glass pill,
 * identical to the zone tooltip's glass treatment) and nothing else.
 */
export default function BeforeAfterToggle({ phase, onChange, preDate, postDate }: BeforeAfterToggleProps) {
  return (
    <div className="before-after-toggle" data-accent-transition>
      <button
        type="button"
        className={`before-after-toggle__option ${phase === 'pre' ? 'before-after-toggle__option--active' : ''}`}
        onClick={() => onChange('pre')}
        aria-pressed={phase === 'pre'}
      >
        <span className="before-after-toggle__label">Pre-Disaster</span>
        <span className="before-after-toggle__date font-mono">{preDate}</span>
      </button>
      <button
        type="button"
        className={`before-after-toggle__option ${phase === 'post' ? 'before-after-toggle__option--active' : ''}`}
        onClick={() => onChange('post')}
        aria-pressed={phase === 'post'}
      >
        <span className="before-after-toggle__label">Post-Disaster</span>
        <span className="before-after-toggle__date font-mono">{postDate}</span>
      </button>
    </div>
  );
}
