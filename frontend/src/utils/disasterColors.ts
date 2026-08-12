import type { DisasterType } from '../types';

/**
 * MapLibre paint properties are evaluated by the WebGL layer and can't
 * read CSS custom properties — they need literal hex strings at layer
 * creation/update time. This is the single source of truth for that,
 * mirroring design-system.css's --accent/--accent-dim/--accent-outline
 * triads exactly so the map and the UI never drift out of sync.
 */
const DISASTER_COLORS: Record<
  DisasterType,
  { primary: string; fill: string; outline: string }
> = {
  flood: { primary: '#1e40af', fill: '#1e3a8a', outline: '#60a5fa' },
  wildfire: { primary: '#dc2626', fill: '#991b1b', outline: '#fca5a5' },
  landslide: { primary: '#92400e', fill: '#78350f', outline: '#fbbf24' },
  cyclone: { primary: '#7c3aed', fill: '#581c87', outline: '#c084fc' },
  earthquake: { primary: '#c2410c', fill: '#9a3412', outline: '#fb923c' },
};

export function getDisasterColor(
  type: DisasterType,
  variant: 'primary' | 'fill' | 'outline' = 'primary',
): string {
  return DISASTER_COLORS[type][variant];
}
