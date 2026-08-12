import { useEffect, useRef } from 'react';
import type { DisasterType, PriorityZone } from '../types';
import PriorityCard from './PriorityCard';
import { IconSatellite } from './icons';
import './PriorityList.css';

interface PriorityListProps {
  zones: PriorityZone[];
  disasterType: DisasterType;
  selectedZoneId: string | null;
  onZoneSelect: (id: string) => void;
  /** IDs currently pinned for comparison (max 2). */
  comparedZoneIds?: string[];
  /** Called when the user clicks the + button on a card. */
  onCompareToggle?: (id: string) => void;
}

export default function PriorityList({
  zones,
  disasterType,
  selectedZoneId,
  onZoneSelect,
  comparedZoneIds = [],
  onCompareToggle,
}: PriorityListProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  // Bumped only on the empty→populated transition (module switch or
  // "analysis complete" reveal), never on a same-list re-render — this is
  // what makes the stagger replay each time zones actually arrive instead
  // of re-animating on every unrelated prop change.
  const entryTokenRef = useRef(0);
  const wasEmptyRef = useRef(true);

  if (zones.length > 0 && wasEmptyRef.current) {
    entryTokenRef.current += 1;
  }
  wasEmptyRef.current = zones.length === 0;

  useEffect(() => {
    if (!selectedZoneId || !containerRef.current) return;
    const el = containerRef.current.querySelector(`[data-zone-id="${selectedZoneId}"]`);
    el?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }, [selectedZoneId]);

  const sorted = [...zones].sort((a, b) => a.priorityRank - b.priorityRank);

  if (sorted.length === 0) {
    return (
      <div className="priority-list__empty">
        <IconSatellite size={22} />
        <p>Select an event to see priority zones</p>
      </div>
    );
  }

  return (
    <div ref={containerRef} className="priority-list">
      {sorted.map((zone, i) => (
        <div
          key={`${zone.zoneId}-${entryTokenRef.current}`}
          className="priority-list__entry"
          style={{ animationDelay: `${i * 60}ms` }}
        >
          <PriorityCard
            zone={zone}
            disasterType={disasterType}
            rank={zone.priorityRank}
            isSelected={zone.zoneId === selectedZoneId}
            onSelect={() => onZoneSelect(zone.zoneId)}
            onCompare={onCompareToggle ? () => onCompareToggle(zone.zoneId) : undefined}
            isCompared={comparedZoneIds.includes(zone.zoneId)}
          />
        </div>
      ))}
    </div>
  );
}
