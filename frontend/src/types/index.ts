/**
 * OrbitalMind — shared domain types.
 *
 * These mirror the backend API contract exactly (see /api/modules,
 * /api/events, /api/events/{id}/zones, /api/narration, /api/report,
 * /api/ws/progress) so mock data and real API responses are
 * interchangeable without adapter code.
 */

/** The five disaster categories the platform supports. */
export type DisasterType =
  | 'flood'
  | 'wildfire'
  | 'landslide'
  | 'cyclone'
  | 'earthquake';

/** Whether a module is running the real ML pipeline or a scripted demo. */
export type ModuleStatus = 'live' | 'demo' | 'coming-soon';

/**
 * One entry in the disaster module navigator (GET /api/modules).
 * This is the metadata that drives the left sidebar — icon, label,
 * status badge, and whether the module can be selected at all.
 */
export interface DisasterModule {
  /** Stable identifier, matches DisasterType. */
  type: DisasterType;
  /** Human-readable name shown in the nav, e.g. "Flood". */
  displayName: string;
  /** Whether this module has a real backend pipeline or mock demo data. */
  status: ModuleStatus;
  /** Short descriptor shown under the name, e.g. "Kerala 2018". */
  regionLabel: string;
  /** Map fly-to target for this disaster's default view. */
  mapCenter: [longitude: number, latitude: number];
  /** Default zoom level when this module is selected. */
  mapZoom: number;
}

/**
 * A specific historical/simulated event within a disaster module
 * (GET /api/events?disaster_type=...). E.g. the Kerala 2018 floods
 * under the "flood" module.
 */
export interface DisasterEvent {
  eventId: string;
  disasterType: DisasterType;
  /** Display name, e.g. "Kerala Floods 2018". */
  name: string;
  /** ISO date string for the event's onset. */
  date: string;
  /** Short one-line summary shown in event pickers. */
  summary: string;
}

/**
 * A single priority zone returned as a GeoJSON Feature's `properties`
 * from GET /api/events/{id}/zones. The geometry itself lives on the
 * enclosing GeoJSON Feature, not here.
 */
export interface PriorityZone {
  zoneId: string;
  zoneName: string;
  /** Model-assigned priority, 0 (lowest) to 1 (highest). */
  priorityScore: number;
  /** 1-indexed rank among all zones in this event, 1 = most urgent. */
  priorityRank: number;
  populationAffected: number;
  hospitalsAffected: number;
  schoolsAffected: number;
  bridgesAtRisk: number;
  /** Percentage (0–100) of roads still passable. */
  roadsIntactPct: number;
  /** Model confidence in this assessment, 0 to 1. */
  confidence: number;
  disasterType: DisasterType;
}

/** GeoJSON FeatureCollection wrapper as returned by /api/events/{id}/zones. */
export interface PriorityZoneCollection {
  type: 'FeatureCollection';
  features: Array<{
    type: 'Feature';
    geometry: import('geojson').Geometry;
    properties: PriorityZone;
  }>;
}

/** GET /api/narration/{event_id}/{zone_id} response. */
export interface NarrationResponse {
  /** Plain-language situation summary for this zone, written for a decision-maker. */
  narration: string;
  /** True if this was served from cache rather than generated fresh. */
  cached: boolean;
}

/** Aggregate stats shown on a module's landing state before a zone is picked. */
export interface PlatformSummary {
  disasterType: DisasterType;
  eventId: string;
  totalZones: number;
  totalPopulationAffected: number;
  criticalZoneCount: number;
  /** 0 to 1, average confidence across all zones. */
  averageConfidence: number;
}

/** POST /api/report/{event_id} response — full payload for PDF generation. */
export interface ReportData {
  eventId: string;
  disasterType: DisasterType;
  eventName: string;
  generatedAt: string;
  summary: PlatformSummary;
  zones: PriorityZone[];
  /** Narration text per zone, keyed by zoneId, for zones that have been analyzed. */
  narrations: Record<string, string>;
}

/** WS /api/ws/progress?task_id=X message shape, streamed 0–100. */
export interface AnalysisProgress {
  taskId: string;
  /** 0 to 100. */
  progress: number;
  /** Short human-readable status, e.g. "Scoring priority zones...". */
  stage: string;
  /** True on the final message of the stream. */
  complete: boolean;
}

/** POST /api/analyze response. */
export interface AnalyzeTaskHandle {
  taskId: string;
}
