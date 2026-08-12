/**
 * Small inline icon set shared by PriorityCard, StatsSummary,
 * NarrationPanel, and PlatformSummary. Same convention as DisasterNav's
 * DisasterIcon: hand-drawn 1.6px stroke, round caps/joins, currentColor —
 * one consistent mark language instead of pulling in an icon library
 * that would read as generic against the rest of the console.
 */

interface IconProps {
  size?: number;
}

const base = (size: number) => ({
  width: size,
  height: size,
  viewBox: '0 0 24 24',
  fill: 'none' as const,
  stroke: 'currentColor',
  strokeWidth: 1.6,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
});

export function IconUsers({ size = 14 }: IconProps) {
  return (
    <svg {...base(size)}>
      <circle cx="9" cy="8" r="3.2" />
      <path d="M3.5 20c.6-3.4 2.9-5.4 5.5-5.4s4.9 2 5.5 5.4" />
      <path d="M16 8.4c1.3.3 2.3 1.4 2.3 3 0 1.2-.6 2.1-1.4 2.6" />
      <path d="M15.5 14.7c2 .5 3.5 2.2 4 4.9" />
    </svg>
  );
}

export function IconHospital({ size = 14 }: IconProps) {
  return (
    <svg {...base(size)}>
      <rect x="4" y="7" width="16" height="14" rx="1.2" />
      <path d="M9 7V4.5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1V7" />
      <path d="M12 11.5v5M9.5 14h5" />
    </svg>
  );
}

export function IconSchool({ size = 14 }: IconProps) {
  return (
    <svg {...base(size)}>
      <path d="M2 9.5 12 5l10 4.5-10 4.5-10-4.5Z" />
      <path d="M6 11.8v4.6c0 1.4 2.7 2.6 6 2.6s6-1.2 6-2.6v-4.6" />
      <path d="M21 9.5v6" />
    </svg>
  );
}

export function IconBridge({ size = 14 }: IconProps) {
  return (
    <svg {...base(size)}>
      <path d="M2 17c2-4 4-6 10-6s8 2 10 6" />
      <path d="M2 17h20M5 17v3M19 17v3M9 17v-3M15 17v-3" />
    </svg>
  );
}

export function IconRoad({ size = 14 }: IconProps) {
  return (
    <svg {...base(size)}>
      <path d="M9 3 4 21M15 3l5 18" />
      <path d="M11.2 9h1.6M10.4 14h3.2" strokeDasharray="0" />
    </svg>
  );
}

export function IconSatellite({ size = 14 }: IconProps) {
  return (
    <svg {...base(size)}>
      <rect x="8.8" y="8.8" width="6.4" height="6.4" rx="1" transform="rotate(45 12 12)" />
      <path d="M6.5 6.5 3.8 3.8M17.5 17.5l2.7 2.7M6.5 17.5l-2.7 2.7M17.5 6.5l2.7-2.7" />
      <path d="M12 15.5 4 21" />
    </svg>
  );
}

export function IconAlert({ size = 14 }: IconProps) {
  return (
    <svg {...base(size)}>
      <path d="M12 3 2 20h20L12 3Z" />
      <path d="M12 10v4.5M12 17v.01" />
    </svg>
  );
}

export function IconShieldCheck({ size = 14 }: IconProps) {
  return (
    <svg {...base(size)}>
      <path d="M12 3 4.5 5.8V11c0 5 3.2 8.3 7.5 10 4.3-1.7 7.5-5 7.5-10V5.8L12 3Z" />
      <path d="M8.5 12.2 11 14.7l4.5-5" />
    </svg>
  );
}

export function IconCopy({ size = 14 }: IconProps) {
  return (
    <svg {...base(size)}>
      <rect x="8.5" y="8.5" width="11" height="11" rx="1.4" />
      <path d="M15.5 8.5V6a1.4 1.4 0 0 0-1.4-1.4H6A1.4 1.4 0 0 0 4.6 6v8.1A1.4 1.4 0 0 0 6 15.5h2.5" />
    </svg>
  );
}

export function IconCheck({ size = 14 }: IconProps) {
  return (
    <svg {...base(size)}>
      <path d="M4.5 12.5 9.5 17.5 19.5 6.5" />
    </svg>
  );
}

export function IconRefresh({ size = 14 }: IconProps) {
  return (
    <svg {...base(size)}>
      <path d="M20 11a8 8 0 0 0-14.9-3.6M4 13a8 8 0 0 0 14.9 3.6" />
      <path d="M5 3v4.4h4.4M19 21v-4.4h-4.4" />
    </svg>
  );
}
