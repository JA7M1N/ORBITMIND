import { useEffect, useRef, useState } from 'react';
import type { DisasterEvent, ModuleStatus } from '../types';
import './EventSelector.css';

interface EventSelectorProps {
  events: DisasterEvent[];
  regionLabel: string;
  moduleStatus: ModuleStatus;
  selectedEventId: string | null;
  onSelectEvent: (eventId: string) => void;
  onRunAnalysis: () => void;
  analyzing: boolean;
  completed: boolean;
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' });
}

export default function EventSelector({
  events,
  regionLabel,
  moduleStatus,
  selectedEventId,
  onSelectEvent,
  onRunAnalysis,
  analyzing,
  completed,
}: EventSelectorProps) {
  // Cross-fade the whole list when the underlying event set changes
  // (i.e. switching disaster modules) — a hard swap reads as a glitch,
  // a brief fade communicates "this is different content now," not
  // "something broke and reloaded."
  const [fading, setFading] = useState(false);
  const eventsKey = events.map((e) => e.eventId).join('|');
  const prevKeyRef = useRef(eventsKey);

  useEffect(() => {
    if (prevKeyRef.current === eventsKey) return;
    prevKeyRef.current = eventsKey;
    setFading(true);
    // Hold at opacity 0 long enough for the 300ms fade-out to actually
    // complete before reversing it — releasing early would cut the dip
    // short and read as a flicker instead of a cross-fade.
    const t = setTimeout(() => setFading(false), 300);
    return () => clearTimeout(t);
  }, [eventsKey]);

  return (
    <div className="event-selector">
      <span className="eyebrow">Event</span>
      <div className={`event-selector__list ${fading ? 'event-selector__list--fading' : ''}`}>
        {events.map((event) => {
          const active = event.eventId === selectedEventId;
          return (
            <button
              key={event.eventId}
              type="button"
              className={`event-card ${active ? 'event-card--active' : ''}`}
              onClick={() => onSelectEvent(event.eventId)}
              aria-pressed={active}
            >
              <div className="event-card__header">
                <span className="event-card__name">{event.name}</span>
                <span className="event-card__date font-mono">{formatDate(event.date)}</span>
              </div>
              <span className="event-card__region">{regionLabel}</span>
              <p className="event-card__summary">{event.summary}</p>
              <span
                className={`status-pill status-pill--${moduleStatus === 'live' ? 'live' : 'demo'}`}
              >
                {moduleStatus === 'live' ? (
                  'LIVE DATA'
                ) : (
                  <>
                    <InfoIcon /> DEMO SCENARIO
                  </>
                )}
              </span>
            </button>
          );
        })}
      </div>

      <button
        type="button"
        className="run-analysis-button"
        onClick={onRunAnalysis}
        disabled={!selectedEventId || analyzing || completed}
      >
        {analyzing ? 'Analyzing…' : completed ? 'Analysis complete' : 'Run analysis'}
      </button>
    </div>
  );
}

function InfoIcon() {
  return (
    <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
      <circle cx="5" cy="5" r="4.25" stroke="currentColor" strokeWidth="1.2" />
      <path d="M5 4.5v2.5M5 3v.01" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
    </svg>
  );
}
