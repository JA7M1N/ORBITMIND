/**
 * SatelliteTimeline
 * =================
 * A horizontal scrubber with 5 satellite acquisition snapshots.
 * Replaces the two-button BeforeAfterToggle with a draggable timeline that
 * shows how the disaster evolved from pre-event baseline to peak extent.
 *
 * Design decisions:
 * - The track itself is the accent colour gradient from left (transparent) to
 *   right (full accent), so even before the user interacts it reads as
 *   "something builds here from left to right."
 * - The thumb is a pulsing radar circle — references the satellite orbit
 *   iconography used elsewhere in the product.
 * - Snapshot labels appear in a tooltip above the thumb on hover/drag —
 *   not as permanent text, which would crowd the bottom-left corner.
 * - Keyboard: ← / → move between snapshots. Home/End jump to first/last.
 * - Auto-play button: steps through all 5 snapshots at 1.2s each.
 */

import { useState, useRef, useCallback, useEffect } from 'react';
import type { DisasterType } from '../types';
import { TIMELINE_SNAPSHOTS } from '../utils/moduleMeta';
import './SatelliteTimeline.css';

// ── Props ─────────────────────────────────────────────────────────────────────

interface SatelliteTimelineProps {
  disasterType: DisasterType;
  /** 0–4 snapshot index, controlled by parent */
  snapshotIndex: number;
  onChange: (index: number) => void;
}

// ── Icons ─────────────────────────────────────────────────────────────────────

function PlayIcon() {
  return (
    <svg width="10" height="10" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M5 3l14 9-14 9V3z" />
    </svg>
  );
}

function PauseIcon() {
  return (
    <svg width="10" height="10" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <rect x="6" y="4" width="4" height="16" rx="1" />
      <rect x="14" y="4" width="4" height="16" rx="1" />
    </svg>
  );
}

// ── Component ─────────────────────────────────────────────────────────────────

const SNAPSHOT_COUNT = 5;

export default function SatelliteTimeline({
  disasterType,
  snapshotIndex,
  onChange,
}: SatelliteTimelineProps) {
  const snapshots = TIMELINE_SNAPSHOTS[disasterType];
  const current   = snapshots[snapshotIndex];

  const [playing,    setPlaying]    = useState(false);
  const [showTooltip, setShowTooltip] = useState(false);
  const playTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const trackRef     = useRef<HTMLDivElement>(null);

  // ── Auto-play logic ────────────────────────────────────────────────────────
  const stopPlay = useCallback(() => {
    if (playTimerRef.current) clearInterval(playTimerRef.current);
    playTimerRef.current = null;
    setPlaying(false);
  }, []);

  const startPlay = useCallback(() => {
    // Reset to 0 if already at the end
    if (snapshotIndex === SNAPSHOT_COUNT - 1) onChange(0);
    setPlaying(true);
    let idx = snapshotIndex === SNAPSHOT_COUNT - 1 ? 0 : snapshotIndex;
    playTimerRef.current = setInterval(() => {
      idx += 1;
      if (idx >= SNAPSHOT_COUNT) {
        stopPlay();
        return;
      }
      onChange(idx);
    }, 1200);
  }, [snapshotIndex, onChange, stopPlay]);

  // Stop auto-play when disaster type changes
  useEffect(() => { stopPlay(); }, [disasterType, stopPlay]);

  // Cleanup on unmount
  useEffect(() => () => { stopPlay(); }, [stopPlay]);

  // ── Track click: jump to nearest snapshot ─────────────────────────────────
  function handleTrackClick(e: React.MouseEvent<HTMLDivElement>) {
    if (!trackRef.current) return;
    const rect  = trackRef.current.getBoundingClientRect();
    const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    const idx   = Math.round(ratio * (SNAPSHOT_COUNT - 1));
    onChange(idx);
    stopPlay();
  }

  // ── Keyboard navigation ───────────────────────────────────────────────────
  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'ArrowRight' || e.key === 'ArrowUp') {
      e.preventDefault();
      onChange(Math.min(snapshotIndex + 1, SNAPSHOT_COUNT - 1));
      stopPlay();
    } else if (e.key === 'ArrowLeft' || e.key === 'ArrowDown') {
      e.preventDefault();
      onChange(Math.max(snapshotIndex - 1, 0));
      stopPlay();
    } else if (e.key === 'Home') {
      e.preventDefault(); onChange(0); stopPlay();
    } else if (e.key === 'End') {
      e.preventDefault(); onChange(SNAPSHOT_COUNT - 1); stopPlay();
    }
  }

  // Thumb position as a % of the track width
  const thumbPct = (snapshotIndex / (SNAPSHOT_COUNT - 1)) * 100;

  return (
    <div className="sat-timeline" data-accent-transition>

      {/* ── Play/Pause button ─────────────────────────────────────────────── */}
      <button
        type="button"
        className={`sat-timeline__play-btn${playing ? ' sat-timeline__play-btn--playing' : ''}`}
        onClick={() => { playing ? stopPlay() : startPlay(); }}
        title={playing ? 'Pause timeline' : 'Auto-play timeline'}
        aria-label={playing ? 'Pause timeline' : 'Play through timeline'}
      >
        {playing ? <PauseIcon /> : <PlayIcon />}
      </button>

      {/* ── Track + ticks + thumb ─────────────────────────────────────────── */}
      <div className="sat-timeline__track-area">

        {/* Snapshot tick marks and date labels */}
        <div className="sat-timeline__ticks">
          {snapshots.map((snap, i) => (
            <button
              key={i}
              type="button"
              className={`sat-timeline__tick${i === snapshotIndex ? ' sat-timeline__tick--active' : ''}`}
              style={{ left: `${(i / (SNAPSHOT_COUNT - 1)) * 100}%` }}
              onClick={() => { onChange(i); stopPlay(); }}
              title={`${snap.date}: ${snap.label}`}
              aria-label={`Snapshot ${i + 1}: ${snap.date}`}
            >
              <span className="sat-timeline__tick-mark" />
              <span className="sat-timeline__tick-date">{snap.date}</span>
            </button>
          ))}
        </div>

        {/* The actual track bar */}
        <div
          ref={trackRef}
          className="sat-timeline__track"
          onClick={handleTrackClick}
          onMouseEnter={() => setShowTooltip(true)}
          onMouseLeave={() => setShowTooltip(false)}
          role="slider"
          aria-label="Satellite acquisition timeline"
          aria-valuemin={0}
          aria-valuemax={SNAPSHOT_COUNT - 1}
          aria-valuenow={snapshotIndex}
          aria-valuetext={`${current.date}: ${current.label}`}
          tabIndex={0}
          onKeyDown={handleKeyDown}
        >
          {/* Fill — grows left to right */}
          <div
            className="sat-timeline__fill"
            style={{ width: `${thumbPct}%` }}
          />

          {/* Thumb — pulsing radar dot */}
          <div
            className={`sat-timeline__thumb${playing ? ' sat-timeline__thumb--playing' : ''}`}
            style={{ left: `${thumbPct}%` }}
          >
            <div className="sat-timeline__thumb-dot" />
            {playing && <div className="sat-timeline__thumb-pulse" />}

            {/* Tooltip — shows on hover/drag or always while playing */}
            {(showTooltip || playing) && (
              <div className="sat-timeline__tooltip">
                <span className="sat-timeline__tooltip-date">{current.date}</span>
                <span className="sat-timeline__tooltip-label">{current.label}</span>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
