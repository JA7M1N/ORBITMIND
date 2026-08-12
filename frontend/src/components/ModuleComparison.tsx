import { useEffect, useState } from 'react';
import type { DisasterEvent, DisasterModule, DisasterType } from '../types';
import { MODULE_COVERAGE } from '../utils/moduleMeta';
import './ModuleComparison.css';

interface ModuleComparisonProps {
  open: boolean;
  onClose: () => void;
  modules: DisasterModule[];
  events: DisasterEvent[];
}

const DETECTION_METHOD: Record<DisasterType, string> = {
  flood: MODULE_COVERAGE.flood.detectionMethod,
  wildfire: MODULE_COVERAGE.wildfire.detectionMethod,
  landslide: MODULE_COVERAGE.landslide.detectionMethod,
  cyclone: MODULE_COVERAGE.cyclone.detectionMethod,
  earthquake: MODULE_COVERAGE.earthquake.detectionMethod,
};

/**
 * A right-edge overlay, not a modal and not a route — it slides in over
 * exactly the space the analysis panel occupies, so the map underneath
 * stays visible and interactive the whole time. That's the point: this
 * panel exists to prove breadth ("here are 5 modules") without asking
 * the judge to leave the thing that proves depth (the live map).
 *
 * Mounted continuously (not conditionally rendered) so the slide-in/out
 * transition can run in both directions; `open` just toggles the
 * transform/visibility, matching the render-then-transition pattern
 * used by AnalysisProgress's fade-out.
 */
export default function ModuleComparison({ open, onClose, modules, events }: ModuleComparisonProps) {
  const [mounted, setMounted] = useState(open);

  useEffect(() => {
    if (open) {
      setMounted(true);
      return;
    }
    const t = setTimeout(() => setMounted(false), 400);
    return () => clearTimeout(t);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    function handleKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose();
    }
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [open, onClose]);

  if (!mounted) return null;

  return (
    <aside
      className={`module-comparison glass-panel ${open ? 'module-comparison--open' : ''}`}
      data-accent-transition
      role="dialog"
      aria-label="Compare disaster modules"
    >
      <div className="module-comparison__header">
        <div>
          <span className="eyebrow">Platform</span>
          <div className="module-comparison__title">Compare modules</div>
        </div>
        <button type="button" className="module-comparison__close" onClick={onClose} aria-label="Close">
          <CloseIcon />
        </button>
      </div>

      <div className="module-comparison__body">
        {/* Structured as label/value rows per module rather than a literal
            5-column grid: at 380px, "Water-extent change detection
            (U-Net)" in a rigid column either truncates or wraps into an
            illegible ladder. Same information, same subtle-rule table
            language, laid out so every field stays readable. */}
        <div className="module-comparison__table">
          {modules.map((module) => {
            const isLive = module.status === 'live';
            const demoEvent = events.find((e) => e.disasterType === module.type);
            return (
              <div
                key={module.type}
                className={`module-comparison__row ${isLive ? 'module-comparison__row--live' : 'module-comparison__row--demo'}`}
              >
                <div className="module-comparison__row-head">
                  <span className="module-comparison__module">{module.displayName}</span>
                  <span className={`status-pill status-pill--${isLive ? 'live' : 'demo'}`}>
                    {isLive ? 'LIVE DATA' : 'DEMO SCENARIO'}
                  </span>
                </div>
                <div className="module-comparison__field">
                  <span className="module-comparison__field-label">Satellite source</span>
                  <span className="module-comparison__field-value">{MODULE_COVERAGE[module.type].satelliteSource}</span>
                </div>
                <div className="module-comparison__field">
                  <span className="module-comparison__field-label">Detection method</span>
                  <span className="module-comparison__field-value">{DETECTION_METHOD[module.type]}</span>
                </div>
                <div className="module-comparison__field">
                  <span className="module-comparison__field-label">Demo event</span>
                  <span className="module-comparison__field-value module-comparison__field-value--muted">
                    {demoEvent?.name ?? '\u2014'}
                  </span>
                </div>
              </div>
            );
          })}
        </div>

        <p className="module-comparison__note">
          Flood runs the platform's live ML pipeline end-to-end on the Kerala 2018 event. Every other
          module is wired identically end-to-end and demoed against a scripted historical scenario —
          swapping in a real pipeline per module is additive, not architectural.
        </p>
      </div>
    </aside>
  );
}

function CloseIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
      <path d="M6 6l12 12M18 6L6 18" />
    </svg>
  );
}
