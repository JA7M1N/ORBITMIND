import { useEffect, useRef, useState } from 'react';
import type { DisasterEvent, DisasterType, PriorityZone } from '../types';
import { IconSatellite, IconAlert, IconUsers, IconShieldCheck } from './icons';
import './StatsSummary.css';

interface StatsSummaryProps {
  zones: PriorityZone[];
  disasterType: DisasterType;
  eventData: DisasterEvent | null;
}

const CRITICAL_LABEL: Record<DisasterType, string> = {
  flood: 'Critical flood zones',
  wildfire: 'Active burn zones',
  landslide: 'High-risk slope zones',
  cyclone: 'Severe impact zones',
  earthquake: 'High-damage zones',
};

function easeOutCubic(t: number): number {
  return 1 - Math.pow(1 - t, 3);
}

/** rAF-driven count-up, not setInterval — the ease-out only reads as
 * smooth at the browser's native paint cadence. Restarts whenever
 * `target` changes (new event, module switch, analysis reveal). */
function useCountUp(target: number, delayMs: number): number {
  const [value, setValue] = useState(0);
  const rafRef = useRef<number | null>(null);

  useEffect(() => {
    if (rafRef.current) cancelAnimationFrame(rafRef.current);
    setValue(0);

    const duration = 1000;
    let start: number | null = null;
    const timer = setTimeout(() => {
      function tick(ts: number) {
        if (start === null) start = ts;
        const elapsed = ts - start;
        const t = Math.min(elapsed / duration, 1);
        setValue(Math.round(easeOutCubic(t) * target));
        if (t < 1) {
          rafRef.current = requestAnimationFrame(tick);
        }
      }
      rafRef.current = requestAnimationFrame(tick);
    }, delayMs);

    return () => {
      clearTimeout(timer);
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, [target, delayMs]);

  return value;
}

function formatNumber(n: number): string {
  return n.toLocaleString('en-IN');
}

export default function StatsSummary({ zones, disasterType }: StatsSummaryProps) {
  const totalZones = zones.length;
  const criticalCount = zones.filter((z) => z.priorityScore >= 0.75).length;
  const totalPopulation = zones.reduce((sum, z) => sum + z.populationAffected, 0);
  const avgConfidence =
    zones.length === 0
      ? 0
      : Math.round((zones.reduce((s, z) => s + z.confidence, 0) / zones.length) * 100);

  const zonesDisplay = useCountUp(totalZones, 0);
  const criticalDisplay = useCountUp(criticalCount, 100);
  const populationDisplay = useCountUp(totalPopulation, 200);
  const confidenceDisplay = useCountUp(avgConfidence, 300);

  // Cross-fade the whole grid on module switch — the numbers themselves
  // already re-animate via useCountUp's target-change restart; this just
  // masks the instant label swap underneath that restart.
  const [fading, setFading] = useState(false);
  const prevTypeRef = useRef(disasterType);
  useEffect(() => {
    if (prevTypeRef.current === disasterType) return;
    prevTypeRef.current = disasterType;
    setFading(true);
    const t = setTimeout(() => setFading(false), 150);
    return () => clearTimeout(t);
  }, [disasterType]);

  return (
    <div className={`stats-summary ${fading ? 'stats-summary--fading' : ''}`}>
      <div className="stats-summary__block">
        <IconSatellite size={16} />
        <div>
          <div className="stats-summary__value font-mono">{zonesDisplay}</div>
          <div className="stats-summary__label">Zones tracked</div>
        </div>
      </div>
      <div className="stats-summary__block">
        <IconAlert size={16} />
        <div>
          <div className="stats-summary__value font-mono">{criticalDisplay}</div>
          <div className="stats-summary__label">{CRITICAL_LABEL[disasterType]}</div>
        </div>
      </div>
      <div className="stats-summary__block">
        <IconUsers size={16} />
        <div>
          <div className="stats-summary__value font-mono">{formatNumber(populationDisplay)}</div>
          <div className="stats-summary__label">Population affected</div>
        </div>
      </div>
      <div className="stats-summary__block">
        <IconShieldCheck size={16} />
        <div>
          <div className="stats-summary__value font-mono">
            {zones.length === 0 ? '—' : `${confidenceDisplay}%`}
          </div>
          <div className="stats-summary__label">Avg. confidence</div>
        </div>
      </div>
    </div>
  );
}
