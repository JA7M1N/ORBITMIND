import type { DisasterType } from '../types';

/**
 * Static platform-coverage metadata per disaster module. This is
 * presentation-layer context (what sensor, what technique) rather than
 * anything the analysis API returns — it describes the platform, not a
 * specific event — so it lives as a frontend constant rather than a
 * mock-data fixture. Both the PDF report (Page 2) and ModuleComparison
 * read from here so the two can never drift out of sync.
 */
export interface ModuleCoverageMeta {
  satelliteSource: string;
  detectionMethod: string;
  /** Text-emoji glyph used on the PDF cover page. */
  emoji: string;
}

/** Pre/post-disaster date labels for the BeforeAfterToggle, per module.
 * Kept for backward compat (PDF report still reads these). */
export const BEFORE_AFTER_DATES: Record<DisasterType, { pre: string; post: string }> = {
  flood:      { pre: 'June 2018',     post: 'August 2018'   },
  wildfire:   { pre: 'March 2024',    post: 'May 2024'      },
  landslide:  { pre: 'June 2023',     post: 'August 2023'   },
  cyclone:    { pre: 'April 2023',    post: 'May 2023'      },
  earthquake: { pre: 'January 2024',  post: 'March 2024'    },
};

export interface TimelineSnapshot {
  /** Short label shown on the scrubber tick */
  date: string;
  /** One-line context: what this pass shows */
  label: string;
  /** 0–1 opacity multiplier for the AffectedZoneLayer at this snapshot.
   *  0 = no inundation visible (pre-disaster baseline),
   *  1 = maximum extent (peak disaster). Non-linear so the mid-disaster
   *  progression reads as dramatic rather than linear. */
  opacity: number;
}

/** Five satellite acquisition snapshots per disaster type.
 *  Index 0 is always the pre-disaster baseline (opacity 0).
 *  Index 4 is always the peak/post-disaster state  (opacity 1). */
export const TIMELINE_SNAPSHOTS: Record<DisasterType, TimelineSnapshot[]> = {
  flood: [
    { date: 'Jun 15',  label: 'Pre-monsoon baseline — normal river levels',              opacity: 0.0  },
    { date: 'Jul 28',  label: 'Monsoon onset — minor overflow in low-lying areas',       opacity: 0.18 },
    { date: 'Aug 06',  label: 'Flooding accelerates — districts begin reporting cuts',   opacity: 0.52 },
    { date: 'Aug 12',  label: 'Peak inundation — Sentinel-1 confirms widest extent',     opacity: 0.82 },
    { date: 'Aug 18',  label: 'Post-peak — water receding, road damage visible',        opacity: 1.0  },
  ],
  wildfire: [
    { date: 'Mar 10',  label: 'Pre-fire baseline — dry season vegetation normal',        opacity: 0.0  },
    { date: 'Apr 02',  label: 'Early ignitions — VIIRS hotspots first detected',         opacity: 0.15 },
    { date: 'Apr 22',  label: 'Fire spread — NBR shows active burn perimeter expanding', opacity: 0.45 },
    { date: 'May 05',  label: 'Peak fire extent — maximum burned area detected',         opacity: 0.80 },
    { date: 'May 15',  label: 'Containment phase — burn scar fully mapped',              opacity: 1.0  },
  ],
  landslide: [
    { date: 'Jun 05',  label: 'Pre-monsoon baseline — slopes stable',                   opacity: 0.0  },
    { date: 'Jul 10',  label: 'Heavy rainfall onset — soil saturation rising',           opacity: 0.20 },
    { date: 'Aug 02',  label: 'First failures — InSAR detects slope displacement',       opacity: 0.50 },
    { date: 'Aug 14',  label: 'Major events — highways and bridges blocked',             opacity: 0.78 },
    { date: 'Aug 20',  label: 'Assessment complete — full debris extent mapped',        opacity: 1.0  },
  ],
  cyclone: [
    { date: 'Apr 25',  label: 'Pre-cyclone baseline — normal coastal conditions',        opacity: 0.0  },
    { date: 'May 01',  label: 'System forming — INSAT-3D tracks depression',             opacity: 0.12 },
    { date: 'May 04',  label: 'Intensification — Category 2, storm surge warning',       opacity: 0.40 },
    { date: 'May 07',  label: 'Landfall — peak winds 145 km/h, surge 2.1m at Puri',    opacity: 0.85 },
    { date: 'May 09',  label: 'Post-landfall — inundation extent confirmed',             opacity: 1.0  },
  ],
  earthquake: [
    { date: 'Jan 20',  label: 'Pre-event baseline — D-InSAR reference acquisition',      opacity: 0.0  },
    { date: 'Feb 14',  label: 'Foreshock sequence — minor deformation detected',         opacity: 0.10 },
    { date: 'Mar 01',  label: 'Mainshock (M6.2) — co-seismic displacement mapped',       opacity: 0.55 },
    { date: 'Mar 10',  label: 'Aftershock sequence — ongoing ground movement',           opacity: 0.80 },
    { date: 'Mar 21',  label: 'Stabilisation — damage assessment complete',              opacity: 1.0  },
  ],
};

export const MODULE_COVERAGE: Record<DisasterType, ModuleCoverageMeta> = {
  flood: {
    satelliteSource: 'Sentinel-1 SAR',
    detectionMethod: 'Water-extent change detection (U-Net)',
    emoji: '\u{1F30A}',
  },
  wildfire: {
    satelliteSource: 'MODIS / VIIRS thermal',
    detectionMethod: 'Active-fire hotspot detection',
    emoji: '\u{1F525}',
  },
  landslide: {
    satelliteSource: 'Sentinel-2 optical + DEM',
    detectionMethod: 'Slope-failure change detection',
    emoji: '\u{1F3D4}\u{FE0F}',
  },
  cyclone: {
    satelliteSource: 'INSAT-3D / 3DR',
    detectionMethod: 'Cloud-top temperature tracking',
    emoji: '\u{1F300}',
  },
  earthquake: {
    satelliteSource: 'Sentinel-1 InSAR',
    detectionMethod: 'Ground-displacement interferometry',
    emoji: '\u{1F30D}',
  },
};
