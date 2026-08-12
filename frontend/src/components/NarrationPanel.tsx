import { useEffect, useRef, useState } from 'react';
import type { DisasterType, NarrationResponse, PriorityZone } from '../types';
import { getNarration } from '../services/api';
import { IconCopy, IconCheck, IconRefresh } from './icons';
import './NarrationPanel.css';

interface NarrationPanelProps {
  eventId: string;
  zone: PriorityZone;
  disasterType: DisasterType;
  /** Fallback narrations used when API is unavailable. */
  narrations: Record<string, NarrationResponse>;
}

const DISASTER_LABEL: Record<DisasterType, string> = {
  flood:     'Flood',
  wildfire:  'Wildfire',
  landslide: 'Landslide',
  cyclone:   'Cyclone',
  earthquake:'Earthquake',
};

const DISASTER_SATELLITE: Record<DisasterType, string> = {
  flood:     'Sentinel-1 SAR',
  wildfire:  'Sentinel-2 SWIR',
  landslide: 'Sentinel-1 InSAR',
  cyclone:   'INSAT-3D',
  earthquake:'Sentinel-1 D-InSAR',
};

const FALLBACK_NARRATION =
  'Situation narration for this zone has not been generated yet. ' +
  'Priority scoring and infrastructure figures above remain accurate.';

function confidenceTier(c: number): 'high' | 'medium' | 'low' {
  if (c > 0.8) return 'high';
  if (c >= 0.6) return 'medium';
  return 'low';
}

type Phase = 'fading' | 'skeleton' | 'content';

/** Ref to the first focusable element inside the narration panel,
 * used for focus management when a zone is selected from the map. */
export type NarrationPanelRef = { focus: () => void };

export default function NarrationPanel({ eventId, zone, disasterType, narrations }: NarrationPanelProps) {
  const [phase,    setPhase]   = useState<Phase>('skeleton');
  const [resolved, setResolved] = useState<NarrationResponse | null>(null);
  const [copied,  setCopied]   = useState(false);
  const timersRef  = useRef<ReturnType<typeof setTimeout>[]>([]);
  const headingRef = useRef<HTMLSpanElement>(null);

  function clearTimers() { timersRef.current.forEach(clearTimeout); timersRef.current = []; }

  async function fetchNarration() {
    clearTimers();

    // 1. Immediately fade existing content to 30% (feels responsive)
    setPhase('fading');
    setResolved(null);

    // 2. At 100ms: switch to skeleton shimmer
    const t1 = setTimeout(() => setPhase('skeleton'), 100);
    timersRef.current.push(t1);

    // 3. Fetch from API (or mock with realistic delay)
    try {
      const data = await getNarration(eventId, zone.zoneId);
      setResolved(data);
      setPhase('content');
    } catch {
      const found = narrations[zone.zoneId];
      setResolved(found ?? { narration: FALLBACK_NARRATION, cached: false });
      setPhase('content');
    }
  }

  useEffect(() => {
    void fetchNarration();
    // Focus the panel heading for accessibility (map zone click → panel focus)
    const ft = setTimeout(() => headingRef.current?.focus(), 150);
    return () => { clearTimers(); clearTimeout(ft); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [zone.zoneId]);

  function handleCopy() {
    if (!resolved) return;
    navigator.clipboard.writeText(resolved.narration).catch(() => {});
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  function handleRefresh() { void fetchNarration(); }

  const tier = confidenceTier(zone.confidence);

  return (
    <div className={`narration-panel narration-panel--${phase}`} data-accent-transition>
      <div className="narration-panel__header">
        {/* tabIndex makes this focusable for keyboard/a11y navigation */}
        <span
          className="narration-panel__zone-name"
          ref={headingRef}
          tabIndex={-1}
          style={{ outline: 'none' }}
        >
          {zone.zoneName}
        </span>
        <span className="narration-panel__badge">
          {DISASTER_LABEL[disasterType]} Module · {DISASTER_SATELLITE[disasterType]}
        </span>
      </div>

      {/* Confidence bar — always renders; width animates in after skeleton appears */}
      <div className="narration-panel__confidence-track">
        <div
          className={`narration-panel__confidence-fill narration-panel__confidence-fill--${tier}`}
          style={{ width: phase === 'fading' ? '0%' : `${zone.confidence * 100}%` }}
        />
      </div>

      {/* Skeleton — shown during fading + skeleton phases */}
      {phase !== 'content' && (
        <div className={`narration-skeleton narration-skeleton--${phase}`} aria-hidden>
          <div className="narration-skeleton__line" style={{ width: '100%' }} />
          <div className="narration-skeleton__line" style={{ width: '92%' }} />
          <div className="narration-skeleton__line" style={{ width: '68%' }} />
        </div>
      )}

      {/* Content — fades in when narration arrives */}
      {phase === 'content' && resolved && (
        <>
          <p className="narration-panel__text narration-panel__text--fadein">
            {resolved.narration}
          </p>

          <div className="narration-panel__source">
            Based on: {zone.hospitalsAffected} hospitals,{' '}
            {zone.populationAffected.toLocaleString('en-IN')} residents,{' '}
            {zone.roadsIntactPct}% roads accessible
          </div>

          <div className="narration-panel__actions">
            <button type="button" className="narration-panel__action" onClick={handleCopy}>
              {copied ? <IconCheck size={13} /> : <IconCopy size={13} />}
              {copied ? 'Copied!' : 'Copy briefing'}
            </button>
            {resolved.cached && (
              <button type="button" className="narration-panel__action" onClick={handleRefresh}>
                <IconRefresh size={13} />
                Refresh
              </button>
            )}
          </div>

          <p className="narration-panel__disclaimer">
            AI-generated — verify with ground reports before operational use.
          </p>
        </>
      )}
    </div>
  );
}
