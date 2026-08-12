import type { DisasterModule, DisasterType } from '../types';
import './DisasterNav.css';

interface DisasterNavProps {
  modules: DisasterModule[];
  activeType: string;
  onSelect: (type: string) => void;
  onCompareModules: () => void;
}

/**
 * Hand-drawn 24px stroke icons, one per disaster type. Built as inline SVG
 * rather than pulled from an icon library so the mark set can share one
 * consistent stroke weight and stay purpose-built for this domain — a
 * generic "warning triangle" icon set from a library would communicate
 * "app that ran out of time," not "purpose-built intelligence platform."
 */
export function DisasterIcon({ type }: { type: DisasterType }) {
  const common = {
    width: 22,
    height: 22,
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 1.6,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
  };

  switch (type) {
    case 'flood':
      return (
        <svg {...common}>
          <path d="M2 16c1.5 1.5 3 1.5 4.5 0s3-1.5 4.5 0 3 1.5 4.5 0 3-1.5 4.5 0" />
          <path d="M2 20c1.5 1.5 3 1.5 4.5 0s3-1.5 4.5 0 3 1.5 4.5 0 3-1.5 4.5 0" />
          <path d="M12 3c2 3 3.5 5.2 3.5 7.2a3.5 3.5 0 1 1-7 0C8.5 8.2 10 6 12 3Z" />
        </svg>
      );
    case 'wildfire':
      return (
        <svg {...common}>
          <path d="M12 2c1 3-2 4-2 7a2 2 0 0 0 4 0c1 1 2 2.5 2 4.5a6 6 0 1 1-12 0C4 9 8 8 12 2Z" />
        </svg>
      );
    case 'landslide':
      return (
        <svg {...common}>
          <path d="M3 20 9 8l3 5 2-3 7 10Z" />
          <path d="M3 20h18" />
          <circle cx="17" cy="6" r="1.4" fill="currentColor" stroke="none" />
        </svg>
      );
    case 'cyclone':
      return (
        <svg {...common}>
          <path d="M4 7c0-2 2-3.5 4.5-3.5S13 5 13 7" />
          <path d="M3 12c0-2.5 2.2-4 5-4s5 1.8 5 4" />
          <path d="M6 17c0-1.8 1.6-3 3.6-3s3.6 1.3 3.6 3" />
          <path d="M12 3v1M20 12h1M12 20v1" opacity=".5" />
        </svg>
      );
    case 'earthquake':
      return (
        <svg {...common}>
          <path d="M2 14h4l2-5 3 9 2.5-6 1.5 2h7" />
        </svg>
      );
  }
}

const STATUS_LABEL: Record<DisasterModule['status'], string> = {
  live: 'Live',
  demo: 'Demo',
  'coming-soon': 'Soon',
};

function DisasterCard({
  module,
  active,
  onSelect,
}: {
  module: DisasterModule;
  active: boolean;
  onSelect: (type: string) => void;
}) {
  const disabled = module.status === 'coming-soon';

  return (
    <button
      type="button"
      className={[
        'disaster-card',
        active ? 'disaster-card--active' : '',
        disabled ? 'disaster-card--disabled' : '',
      ]
        .filter(Boolean)
        .join(' ')}
      onClick={() => !disabled && onSelect(module.type)}
      disabled={disabled}
      aria-pressed={active}
    >
      <span className="disaster-card__icon">
        <DisasterIcon type={module.type} />
      </span>

      <span className="disaster-card__body">
        <span className="disaster-card__name">{module.displayName}</span>
        <span className="disaster-card__region">{module.regionLabel}</span>
        <span className="disaster-card__status">
          <span
            className={`disaster-card__status-dot disaster-card__status-dot--${
              module.status === 'live' ? 'live' : 'demo'
            }`}
          />
          <span className="disaster-card__status-label">
            {STATUS_LABEL[module.status]}
          </span>
        </span>
      </span>

      {disabled && (
        <span className="disaster-card__tooltip">Coming soon</span>
      )}
    </button>
  );
}

export default function DisasterNav({
  modules,
  activeType,
  onSelect,
  onCompareModules,
}: DisasterNavProps) {
  return (
    <nav className="disaster-nav" aria-label="Disaster modules">
      <div className="disaster-nav__brand">
        <span className="disaster-nav__brand-mark">OrbitalMind</span>
      </div>

      <div className="disaster-nav__list">
        {modules.map((module) => (
          <DisasterCard
            key={module.type}
            module={module}
            active={module.type === activeType}
            onSelect={onSelect}
          />
        ))}
      </div>

      <div className="disaster-nav__footer">
        <button type="button" className="disaster-nav__compare-link" onClick={onCompareModules}>
          <CompareIcon />
          Compare modules
        </button>
      </div>
    </nav>
  );
}

function CompareIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="4" width="8" height="16" rx="1.2" />
      <rect x="13" y="4" width="8" height="16" rx="1.2" />
      <path d="M7 9v6M17 9v6" />
    </svg>
  );
}
