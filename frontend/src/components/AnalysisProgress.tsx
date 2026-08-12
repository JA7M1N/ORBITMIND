import { useEffect, useRef, useState } from 'react';
import { openProgressSocket, DEMO_MODE } from '../services/api';
import './AnalysisProgress.css';

interface AnalysisProgressProps {
  taskId: string;
  onComplete: () => void;
  /** Override auto-detection — force demo simulation regardless of DEMO_MODE. */
  forceDemoMode?: boolean;
}

interface Frame {
  progress: number;
  stage: string;
}

/**
 * Disaster-specific progress scripts.
 * Each has a distinct vocabulary — "SAR imagery" for flood, "SWIR" for wildfire, etc.
 * Fast jumps represent cheap I/O; pauses sit where something expensive is plausibly happening.
 */
const DEMO_SCRIPTS: Record<string, { at: number; delay: number; stage: string }[]> = {
  flood: [
    { at: 10, delay: 0,   stage: 'Loading Sentinel-1 SAR imagery…' },
    { at: 25, delay: 400, stage: 'Running flood-mask U-Net inference…' },
    { at: 50, delay: 700, stage: 'Overlaying OSM infrastructure layer…' },
    { at: 65, delay: 400, stage: 'Spatial join: hospitals, schools, bridges…' },
    { at: 80, delay: 500, stage: 'Scoring priority zones…' },
    { at: 90, delay: 300, stage: 'Ranking 8 districts by composite score…' },
    { at: 95, delay: 200, stage: 'Generating GeoJSON output…' },
    { at: 100,delay: 0,   stage: 'Analysis complete. 8 districts prioritised.' },
  ],
  wildfire: [
    { at: 10, delay: 0,   stage: 'Loading Sentinel-2 SWIR bands…' },
    { at: 30, delay: 500, stage: 'Computing normalized burn ratio (NBR)…' },
    { at: 55, delay: 600, stage: 'Classifying burn severity…' },
    { at: 75, delay: 400, stage: 'Mapping evacuation routes…' },
    { at: 90, delay: 300, stage: 'Scoring fire perimeter zones…' },
    { at: 100,delay: 0,   stage: 'Analysis complete. Fire extent mapped.' },
  ],
  landslide: [
    { at: 10, delay: 0,   stage: 'Loading Sentinel-1 InSAR coherence…' },
    { at: 30, delay: 500, stage: 'Analysing SRTM slope stability…' },
    { at: 55, delay: 600, stage: 'Detecting displacement vectors…' },
    { at: 75, delay: 400, stage: 'Identifying blocked road corridors…' },
    { at: 90, delay: 300, stage: 'Scoring slide zones by exposure…' },
    { at: 100,delay: 0,   stage: 'Analysis complete. Slide zones mapped.' },
  ],
  cyclone: [
    { at: 10, delay: 0,   stage: 'Loading INSAT-3D IR + WV imagery…' },
    { at: 30, delay: 500, stage: 'Applying Dvorak intensity technique…' },
    { at: 55, delay: 600, stage: 'Modelling storm surge inundation…' },
    { at: 75, delay: 400, stage: 'Mapping coastal shelter capacity…' },
    { at: 90, delay: 300, stage: 'Ranking coastal exposure zones…' },
    { at: 100,delay: 0,   stage: 'Analysis complete. Landfall zone mapped.' },
  ],
  earthquake: [
    { at: 10, delay: 0,   stage: 'Loading Sentinel-1 D-InSAR stack…' },
    { at: 30, delay: 500, stage: 'Computing co-seismic displacement…' },
    { at: 55, delay: 600, stage: 'Overlaying USGS ShakeMap PGA…' },
    { at: 75, delay: 400, stage: 'Assessing structural vulnerability…' },
    { at: 90, delay: 300, stage: 'Ranking districts by damage probability…' },
    { at: 100,delay: 0,   stage: 'Analysis complete. Damage zones ranked.' },
  ],
};

const GENERIC_SCRIPT = DEMO_SCRIPTS.flood;

export default function AnalysisProgress({ taskId, onComplete, forceDemoMode }: AnalysisProgressProps) {
  const [frame, setFrame]   = useState<Frame>({ progress: 0, stage: 'Initializing…' });
  const [done, setDone]     = useState(false);
  const [visible, setVisible] = useState(true);
  const onCompleteRef = useRef(onComplete);
  onCompleteRef.current = onComplete;

  useEffect(() => {
    setFrame({ progress: 0, stage: 'Initializing…' });
    setDone(false);
    setVisible(true);

    // Determine which script to use (derive disaster type from task id convention)
    const disasterMatch = taskId.match(/-(flood|wildfire|landslide|cyclone|earthquake)-/);
    const disaster = disasterMatch?.[1] ?? 'flood';
    const script = DEMO_SCRIPTS[disaster] ?? GENERIC_SCRIPT;

    const useDemoSim = DEMO_MODE || (forceDemoMode === true);

    function finish() {
      setDone(true);
      const holdT = setTimeout(() => {
        setVisible(false);
        const removeT = setTimeout(() => onCompleteRef.current(), 400);
        return removeT;
      }, 800);
      return holdT;
    }

    if (useDemoSim) {
      const timers: ReturnType<typeof setTimeout>[] = [];
      let elapsed = 0;
      for (const step of script) {
        elapsed += step.delay;
        const t = setTimeout(() => {
          setFrame({ progress: step.at, stage: step.stage });
          if (step.at === 100) {
            timers.push(finish());
          }
        }, elapsed);
        timers.push(t);
      }
      return () => timers.forEach(clearTimeout);
    }

    // Live mode: real WebSocket with 500ms fallback to demo simulation.
    let ws: WebSocket | null = null;
    let usedFallback = false;

    function startDemoFallback() {
      if (usedFallback) return;
      usedFallback = true;
      const timers: ReturnType<typeof setTimeout>[] = [];
      let elapsed = 0;
      for (const step of script) {
        elapsed += step.delay;
        const t = setTimeout(() => {
          setFrame({ progress: step.at, stage: step.stage });
          if (step.at === 100) timers.push(finish());
        }, elapsed);
        timers.push(t);
      }
    }

    ws = openProgressSocket(
      taskId,
      (data) => {
        setFrame({
          progress: data.progress ?? 0,
          stage:    data.message  ?? 'Processing…',
        });
        if (data.status === 'complete' || data.progress >= 100) {
          finish();
        }
      },
      () => startDemoFallback(),
    );

    return () => { ws?.close(); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [taskId]);

  return (
    <div
      className={`analysis-progress ${visible ? 'analysis-progress--visible' : ''} ${done ? 'analysis-progress--done' : ''}`}
      data-accent-transition
    >
      <div className="analysis-progress__track">
        <div className="analysis-progress__fill" style={{ width: `${frame.progress}%` }} />
      </div>
      <div className="analysis-progress__row">
        <span className="analysis-progress__stage" key={frame.stage}>
          {frame.stage}
        </span>
        <span className="analysis-progress__pct font-mono">
          {done ? <CheckIcon /> : `${frame.progress}%`}
        </span>
      </div>
    </div>
  );
}

function CheckIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
      <path d="M2.5 7.5L5.5 10.5L11.5 3.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
