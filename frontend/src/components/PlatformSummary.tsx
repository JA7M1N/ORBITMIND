/**
 * PlatformSummary — Cinematic Welcome Screen
 * ============================================
 * Full-screen module selector that replaces the old chip-row design.
 *
 * Layout:
 *  - Top: orbital SVG animation + headline + tagline (stagger-in)
 *  - Bottom: 5 module cards arranged in a row, each revealing on stagger
 *
 * Each module card shows:
 *  - Large disaster emoji / icon
 *  - Module name + satellite source
 *  - Status badge (LIVE / DEMO)
 *  - A subtle "scan line" animation while hovered
 *  - Click → onSelectModule
 */

import { useState } from 'react';
import type { DisasterModule } from '../types';
import { MODULE_COVERAGE } from '../utils/moduleMeta';
import './PlatformSummary.css';

interface PlatformSummaryProps {
  modules: DisasterModule[];
  onSelectModule: (type: string) => void;
}

// ── Orbital ring SVG — pure CSS animated ─────────────────────────────────────

function OrbitalRings() {
  return (
    <svg
      className="ps-orbital"
      viewBox="0 0 320 320"
      fill="none"
      aria-hidden="true"
    >
      {/* Outer ring */}
      <ellipse
        cx="160" cy="160" rx="148" ry="60"
        stroke="rgba(255,255,255,0.06)"
        strokeWidth="1"
        className="ps-orbital__ring ps-orbital__ring--outer"
      />
      {/* Middle ring */}
      <ellipse
        cx="160" cy="160" rx="108" ry="44"
        stroke="rgba(255,255,255,0.08)"
        strokeWidth="1"
        className="ps-orbital__ring ps-orbital__ring--mid"
      />
      {/* Inner ring */}
      <ellipse
        cx="160" cy="160" rx="70" ry="28"
        stroke="rgba(255,255,255,0.1)"
        strokeWidth="1"
        className="ps-orbital__ring ps-orbital__ring--inner"
      />
      {/* Globe circle */}
      <circle
        cx="160" cy="160" r="28"
        fill="rgba(255,255,255,0.04)"
        stroke="rgba(255,255,255,0.12)"
        strokeWidth="1"
      />
      {/* Globe latitude lines */}
      <ellipse cx="160" cy="160" rx="28" ry="10" stroke="rgba(255,255,255,0.06)" strokeWidth="0.5" />
      <line x1="132" y1="160" x2="188" y2="160" stroke="rgba(255,255,255,0.06)" strokeWidth="0.5" />
      <line x1="160" y1="132" x2="160" y2="188" stroke="rgba(255,255,255,0.06)" strokeWidth="0.5" />

      {/* Satellite dot — outer ring, animated via CSS */}
      <circle r="3" fill="currentColor" className="ps-orbital__sat ps-orbital__sat--outer" opacity="0.7">
        <animateMotion dur="8s" repeatCount="indefinite">
          <mpath href="#outer-path" />
        </animateMotion>
      </circle>
      {/* Satellite dot — mid ring */}
      <circle r="2.5" fill="currentColor" className="ps-orbital__sat ps-orbital__sat--mid" opacity="0.5">
        <animateMotion dur="5s" repeatCount="indefinite" begin="-2s">
          <mpath href="#mid-path" />
        </animateMotion>
      </circle>

      {/* Hidden motion paths */}
      <defs>
        <path id="outer-path" d="M 308,160 A 148,60 0 1,1 307.9,160" />
        <path id="mid-path"   d="M 268,160 A 108,44 0 1,1 267.9,160" />
      </defs>
    </svg>
  );
}

// ── Disaster emoji map ────────────────────────────────────────────────────────

const DISASTER_EMOJI: Record<string, string> = {
  flood:      '🌊',
  wildfire:   '🔥',
  landslide:  '🏔️',
  cyclone:    '🌀',
  earthquake: '🌍',
};

const DISASTER_ACCENT: Record<string, string> = {
  flood:      '#3b82f6',
  wildfire:   '#f97316',
  landslide:  '#a3855c',
  cyclone:    '#8b5cf6',
  earthquake: '#ef4444',
};

// ── Module card ───────────────────────────────────────────────────────────────

interface ModuleCardProps {
  module: DisasterModule;
  index: number;
  onSelect: () => void;
}

function ModuleCard({ module, index, onSelect }: ModuleCardProps) {
  const [hovered, setHovered] = useState(false);
  const meta    = MODULE_COVERAGE[module.type];
  const emoji   = DISASTER_EMOJI[module.type] ?? '🛰️';
  const accent  = DISASTER_ACCENT[module.type] ?? '#64748b';
  const isLive  = module.status === 'live';

  return (
    <button
      type="button"
      className={`ps-card${isLive ? ' ps-card--live' : ''}${hovered ? ' ps-card--hovered' : ''}`}
      style={{
        '--card-accent': accent,
        animationDelay: `${180 + index * 90}ms`,
      } as React.CSSProperties}
      onClick={onSelect}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      aria-label={`Launch ${module.displayName} module`}
    >
      {/* Scan-line overlay — only visible on hover */}
      <div className="ps-card__scanline" aria-hidden="true" />

      {/* Glow */}
      <div className="ps-card__glow" aria-hidden="true" />

      {/* Status badge */}
      <div className={`ps-card__status ps-card__status--${isLive ? 'live' : 'demo'}`}>
        <span className="ps-card__status-dot" />
        {isLive ? 'LIVE' : 'DEMO'}
      </div>

      {/* Emoji */}
      <div className="ps-card__emoji" aria-hidden="true">{emoji}</div>

      {/* Name */}
      <div className="ps-card__name">{module.displayName}</div>

      {/* Satellite source */}
      <div className="ps-card__source">{meta.satelliteSource}</div>

      {/* Method */}
      <div className="ps-card__method">{meta.detectionMethod}</div>

      {/* Launch arrow */}
      <div className="ps-card__arrow" aria-hidden="true">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M5 12h14M12 5l7 7-7 7"/>
        </svg>
      </div>
    </button>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export default function PlatformSummary({ modules, onSelectModule }: PlatformSummaryProps) {
  const [exiting, setExiting] = useState(false);

  function handleSelect(type: string) {
    if (exiting) return;
    setExiting(true);
    // Let the exit animation play (280ms), then hand off
    setTimeout(() => onSelectModule(type), 280);
  }

  return (
    <div className={`platform-summary${exiting ? ' platform-summary--exiting' : ''}`}>
      {/* Animated grid backdrop */}
      <div className="ps-backdrop" aria-hidden="true">
        <div className="ps-backdrop__grid" />
        <div className="ps-backdrop__radial" />
        <div className="ps-backdrop__scanline-h" />
      </div>

      {/* Hero section */}
      <div className="ps-hero">
        <OrbitalRings />

        <div className="ps-hero__text">
          <span className="ps-hero__eyebrow">
            <span className="ps-hero__eyebrow-dot" />
            OrbitalMind · v2.0
          </span>
          <h1 className="ps-hero__heading">
            Multi-Disaster<br />
            <span className="ps-hero__heading-accent">Intelligence Platform</span>
          </h1>
          <p className="ps-hero__tagline">
            Satellite-powered priority scoring for flood, wildfire,<br />
            landslide, cyclone &amp; earthquake response.
          </p>
        </div>
      </div>

      {/* Module cards */}
      <div className="ps-cards" role="list">
        {modules.map((module, i) => (
          <div role="listitem" key={module.type}>
            <ModuleCard
              module={module}
              index={i}
              onSelect={() => handleSelect(module.type)}
            />
          </div>
        ))}
      </div>

      {/* Bottom hint */}
      <p className="ps-hint">
        Select a module to begin satellite analysis
      </p>
    </div>
  );
}
