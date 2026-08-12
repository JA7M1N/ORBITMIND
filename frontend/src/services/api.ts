/**
 * OrbitalMind API Client
 * ========================
 * Single integration boundary between the UI and the backend.
 *
 * Flip strategy (VITE_DEMO_MODE):
 *   true  → return mock data after 300 ms (simulates realistic network latency)
 *   false → call real API endpoint; on any network error or 5xx, log a warning,
 *           show an amber toast, and silently fall back to mock data so the
 *           demo never shows a blank screen or an error state.
 *
 * Every function returns the same TypeScript type regardless of which path
 * it took — no adapter code needed in components.
 */

import axios, { type AxiosError } from 'axios';
import { toast } from 'react-toastify';
import type {
  DisasterModule,
  DisasterEvent,
  DisasterType,
  NarrationResponse,
} from '../types';
import {
  MOCK_MODULES,
  MOCK_EVENTS,
  MOCK_ZONES_BY_DISASTER,
  MOCK_NARRATIONS,
} from '../mock/mockData';

// ── Config ────────────────────────────────────────────────────────────────────

const DEMO_MODE = import.meta.env.VITE_DEMO_MODE === 'true';
const API_URL   = (import.meta.env.VITE_API_URL as string | undefined) ?? 'http://localhost:8000';
export const WS_URL = (import.meta.env.VITE_WS_URL as string | undefined) ?? 'ws://localhost:8000';

export { DEMO_MODE };

const http = axios.create({
  baseURL: API_URL,
  timeout: 15_000,
});

// ── Shared helpers ─────────────────────────────────────────────────────────────

/** Simulated network latency for demo mode — feels real without being annoying. */
function mockDelay<T>(value: T, ms = 300): Promise<T> {
  return new Promise((resolve) => setTimeout(() => resolve(value), ms));
}

let _toastShown = false;
function warnFallback(endpoint: string, err: unknown) {
  console.warn(`[OrbitalMind] API call to ${endpoint} failed — using cached data.`, err);
  if (!_toastShown) {
    _toastShown = true;
    toast.warn('Using cached data — backend unavailable', {
      position: 'bottom-right',
      autoClose: 4000,
      hideProgressBar: false,
      closeOnClick: true,
      theme: 'dark',
      style: {
        background: '#1c1410',
        borderLeft: '3px solid #f59e0b',
        color: '#fde68a',
        fontSize: '13px',
        fontFamily: 'Inter, sans-serif',
      },
      onClose: () => { _toastShown = false; },
    });
  }
}

/** Normalise a backend module to the frontend DisasterModule shape. */
function normaliseModule(raw: Record<string, unknown>): DisasterModule {
  const type = (raw['disaster_type'] as DisasterType) ?? (raw['type'] as DisasterType);
  const mock  = MOCK_MODULES.find((m) => m.type === type);
  return {
    type,
    displayName: (raw['display_name'] as string) ?? mock?.displayName ?? String(type),
    status:      (raw['status'] as DisasterModule['status']) ?? 'demo',
    regionLabel: mock?.regionLabel ?? '',
    mapCenter:   mock?.mapCenter  ?? [78.9629, 20.5937],
    mapZoom:     mock?.mapZoom    ?? 8,
  };
}

/** Normalise a backend event to the frontend DisasterEvent shape. */
function normaliseEvent(raw: Record<string, unknown>): DisasterEvent {
  const dtype = ((raw['disaster_type'] ?? raw['disasterType']) as DisasterType);
  const eventId = (raw['event_id'] ?? raw['eventId'] ?? '') as string;
  return {
    eventId,
    disasterType: dtype,
    name:    (raw['display_name'] ?? raw['name'] ?? eventId) as string,
    date:    (raw['date_start']   ?? raw['date'] ?? '') as string,
    summary: (raw['description']  ?? raw['summary'] ?? '') as string,
  };
}

// ── API functions ─────────────────────────────────────────────────────────────

/**
 * GET /api/modules
 * Returns the 5 disaster modules with status, color, icon, etc.
 */
export async function getModules(): Promise<DisasterModule[]> {
  if (DEMO_MODE) return mockDelay(MOCK_MODULES);
  try {
    const { data } = await http.get<Record<string, unknown>[]>('/api/modules');
    return data.map(normaliseModule);
  } catch (err) {
    warnFallback('/api/modules', err as AxiosError);
    return MOCK_MODULES;
  }
}

/**
 * GET /api/events?disaster_type=<type>
 * Returns events filtered by disaster type, or all events if omitted.
 */
export async function getEvents(disasterType?: DisasterType): Promise<DisasterEvent[]> {
  if (DEMO_MODE) {
    const filtered = disasterType
      ? MOCK_EVENTS.filter((e) => e.disasterType === disasterType)
      : MOCK_EVENTS;
    return mockDelay(filtered);
  }
  try {
    const params = disasterType ? { disaster_type: disasterType } : {};
    const { data } = await http.get<Record<string, unknown>[]>('/api/events', { params });
    return data.map(normaliseEvent);
  } catch (err) {
    warnFallback('/api/events', err as AxiosError);
    return disasterType ? MOCK_EVENTS.filter((e) => e.disasterType === disasterType) : MOCK_EVENTS;
  }
}

/**
 * POST /api/analyze
 * Starts a background analysis task. Returns task_id for WebSocket tracking.
 */
export async function triggerAnalysis(
  eventId: string,
  disasterType: DisasterType,
): Promise<{ task_id: string }> {
  if (DEMO_MODE) {
    return mockDelay({ task_id: `demo-${disasterType}-${Date.now()}` }, 150);
  }
  try {
    const { data } = await http.post<{ task_id: string }>('/api/analyze', {
      event_id:     eventId,
      disaster_type: disasterType,
      demo_mode:    false,
    });
    return data;
  } catch (err) {
    warnFallback('/api/analyze', err as AxiosError);
    return { task_id: `fallback-${disasterType}-${Date.now()}` };
  }
}

/**
 * GET /api/events/{eventId}/zones
 * Returns the GeoJSON FeatureCollection with priority zone properties.
 */
export async function getZones(eventId: string, disasterType: DisasterType) {
  if (DEMO_MODE) {
    return mockDelay(MOCK_ZONES_BY_DISASTER[disasterType]);
  }
  try {
    const normId = eventId.replace(/-/g, '_');
    const { data } = await http.get(`/api/events/${normId}/zones`);
    // Backend returns affected_zones_geojson; extract and return that
    const fc = data?.affected_zones_geojson ?? data;
    if (fc?.type === 'FeatureCollection') {
      // Normalise feature properties to match frontend PriorityZone shape
      return {
        ...fc,
        features: fc.features.map((feat: Record<string, unknown>) => {
          const p = feat['properties'] as Record<string, unknown>;
          return {
            ...feat,
            properties: {
              zoneId:             (p['zone_id']     ?? p['zoneId']     ?? '') as string,
              zoneName:           (p['zone_name']   ?? p['zone']       ?? '') as string,
              priorityScore:      Number(p['priority_score'] ?? p['priorityScore'] ?? p['score'] ?? 0),
              priorityRank:       Number(p['priority_rank']  ?? p['priorityRank']  ?? p['rank']  ?? 1),
              populationAffected: Number(p['population']     ?? p['pop']           ?? 0),
              hospitalsAffected:  Number(p['hospitals']      ?? p['hospitals_affected'] ?? 0),
              schoolsAffected:    Number(p['schools']        ?? p['schools_affected']   ?? 0),
              bridgesAtRisk:      Number(p['bridges']        ?? p['bridges_affected']   ?? 0),
              roadsIntactPct:     Number(p['road_pct']       ?? p['roads_intact_pct']   ?? 65),
              confidence:         Number(p['confidence']     ?? 0.75),
              disasterType,
            },
          };
        }),
      };
    }
    return MOCK_ZONES_BY_DISASTER[disasterType];
  } catch (err) {
    warnFallback(`/api/events/${eventId}/zones`, err as AxiosError);
    return MOCK_ZONES_BY_DISASTER[disasterType];
  }
}

/**
 * GET /api/narration/{eventId}/{zoneId}
 * Returns LLM-generated briefing text for a single zone.
 */
export async function getNarration(
  eventId: string,
  zoneId:  string,
): Promise<NarrationResponse> {
  if (DEMO_MODE) {
    // Simulate 800–1600ms LLM generation latency
    const delay = 800 + Math.random() * 800;
    const found = MOCK_NARRATIONS[zoneId];
    return mockDelay(
      found ?? { narration: FALLBACK_NARRATION, cached: false },
      delay,
    );
  }
  try {
    // Normalise event ID format for the backend (kerala-2018 or kerala_2018 both work)
    const normEvent = eventId.replace(/_/g, '-');
    const normZone  = zoneId.replace(/^zone-/, '').replace(/_/g, '-');
    const { data } = await http.get<{ narration: string; cached: boolean; source: string }>(
      `/api/narration/${normEvent}/${normZone}`,
    );
    return { narration: data.narration, cached: data.cached ?? (data.source !== 'ollama') };
  } catch (err) {
    warnFallback(`/api/narration/${eventId}/${zoneId}`, err as AxiosError);
    const found = MOCK_NARRATIONS[zoneId];
    return found ?? { narration: FALLBACK_NARRATION, cached: false };
  }
}

/**
 * POST /api/report/{eventId}
 * Generates the full incident report. The frontend PDF generator consumes this.
 */
export async function getReport(eventId: string) {
  if (DEMO_MODE) return mockDelay(null, 200); // frontend builds report from local state
  try {
    const normId = eventId.replace(/_/g, '-');
    const { data } = await http.post(`/api/report/${normId}?narrate=false&top_n=8`);
    return data;
  } catch (err) {
    warnFallback(`/api/report/${eventId}`, err as AxiosError);
    return null;
  }
}

/**
 * GET /api/platform/summary
 * Returns aggregate stats for the platform dashboard (PlatformSummary component).
 */
export async function getPlatformSummary() {
  if (DEMO_MODE) {
    return mockDelay({
      total_modules: 5,
      live_modules:  1,
      demo_modules:  4,
      total_events_tracked: 5,
      disasters_covered: ['flood', 'wildfire', 'landslide', 'cyclone', 'earthquake'],
      totals: {
        total_pop_affected:  43_580_556,
        total_area_km2:      15_730,
        total_zones_scored:  37,
      },
    }, 200);
  }
  try {
    const { data } = await http.get('/api/platform/summary');
    return data;
  } catch (err) {
    warnFallback('/api/platform/summary', err as AxiosError);
    return null;
  }
}

// ── WebSocket factory ─────────────────────────────────────────────────────────

/**
 * Open a progress WebSocket for a real analysis task.
 * Returns null immediately if the URL is invalid or connection fails within 500ms.
 * The caller should fall back to demo simulation in that case.
 */
export function openProgressSocket(
  taskId: string,
  onMessage: (data: { progress: number; message: string; status: string; result?: unknown }) => void,
  onFail: () => void,
): WebSocket | null {
  if (DEMO_MODE) { onFail(); return null; }
  try {
    const ws = new WebSocket(`${WS_URL}/api/ws/progress?task_id=${taskId}`);
    const failTimer = setTimeout(() => {
      if (ws.readyState !== WebSocket.OPEN) {
        ws.close();
        onFail();
      }
    }, 500);

    ws.onopen  = () => clearTimeout(failTimer);
    ws.onerror = () => { clearTimeout(failTimer); onFail(); };
    ws.onmessage = (evt) => {
      try { onMessage(JSON.parse(evt.data as string) as Parameters<typeof onMessage>[0]); }
      catch { /* ignore malformed frame */ }
    };
    return ws;
  } catch {
    onFail();
    return null;
  }
}

const FALLBACK_NARRATION =
  'Situation narration for this zone has not been generated yet. ' +
  'Priority scoring and infrastructure figures above remain accurate.';

// ── Copilot API ───────────────────────────────────────────────────────────────

import type { MapAction, CopilotSuggestions } from '../types/copilot';

/** Keyword-matched demo responses — keyed by disaster type so each module
 * gets contextually correct answers. The flood table is the most detailed
 * (it mirrors the Kerala 2018 copilot_service.py fixtures exactly).
 */
type MockResponse = { keywords: string[]; reply: string; mapAction?: MapAction };

const _MOCK_RESPONSES_BY_DISASTER: Record<string, MockResponse[]> = {

  // ── Flood · Kerala 2018 ──────────────────────────────────────────────────
  flood: [
    {
      keywords: ['thrissur', 'show thrissur', 'navigate', 'go to', 'zoom'],
      reply: 'Thrissur is ranked 6th with a priority score of 0.64. Road accessibility is 67% — better than most zones. Nine hospitals are in the impact zone.',
      mapAction: { action: 'ZOOM', target: 'Thrissur' },
    },
    {
      keywords: ['idukki'],
      reply: 'Idukki is the highest priority zone with a score of 0.94. Only 38% of roads remain passable and 6 hospitals are inside the flood boundary. Prioritise helicopter-based rescue there immediately.',
      mapAction: { action: 'ZOOM', target: 'Idukki' },
    },
    {
      keywords: ['alappuzha'],
      reply: 'Alappuzha is ranked 2nd with a priority score of 0.89 and 412,300 people affected — the second largest affected population.',
      mapAction: { action: 'ZOOM', target: 'Alappuzha' },
    },
    {
      keywords: ['kottayam'],
      reply: 'Kottayam is ranked 3rd with a priority score of 0.82. Road accessibility is 52% and 8 hospitals are in the flood zone.',
      mapAction: { action: 'ZOOM', target: 'Kottayam' },
    },
    {
      keywords: ['ernakulam'],
      reply: 'Ernakulam is ranked 5th. It has the highest hospital count — 14 hospitals in the flood zone — and the largest affected population at 521,400.',
      mapAction: { action: 'ZOOM', target: 'Ernakulam' },
    },
    {
      keywords: ['hospital', 'hospitals', 'perimeter', 'near'],
      reply: 'Ernakulam has 14 hospitals inside the flood zone — the highest of any district. Alappuzha follows with 11. Hospital layer highlighted.',
      mapAction: { action: 'HIGHLIGHT', layer: 'hospitals' },
    },
    {
      keywords: ['road', 'roads', 'access', 'passable'],
      reply: 'Idukki has the worst road accessibility at 38%, followed by Pathanamthitta at 41%. Both require helicopter logistics.',
      mapAction: { action: 'HIGHLIGHT', layer: 'roads' },
    },
    {
      keywords: ['bridge', 'bridges'],
      reply: 'Idukki has 9 bridges at risk — the most of any district. Wayanad follows with 6.',
      mapAction: { action: 'HIGHLIGHT', layer: 'bridges' },
    },
    {
      keywords: ['rescue', 'boat', 'first', 'priority', 'which district'],
      reply: 'Idukki should receive rescue boats first — priority score 0.94, only 38% roads passable, 9 bridges at risk, and 6 hospitals in the flood zone. Alappuzha is second with 412,300 people affected.',
    },
    {
      keywords: ['population', 'people', 'affected', 'how many'],
      reply: 'Ernakulam has the largest affected population at 521,400. Alappuzha follows with 412,300. Combined that is over 930,000 residents in the flood zone.',
    },
    {
      keywords: ['draft', 'alert', 'advisory', 'order', 'write'],
      reply: 'EMERGENCY ALERT — IDUKKI DISTRICT: Severe flood inundation confirmed via Sentinel-1 SAR analysis dated 08 August 2018. Road accessibility at 38%. All residents in low-lying areas must evacuate immediately to designated relief camps.',
    },
    {
      keywords: ['confidence', 'accurate', 'reliable'],
      reply: 'Average detection confidence across all 8 zones is 84%. Idukki is highest at 91%, Wayanad lowest at 79%. All figures derived from Sentinel-1 C-band SAR backscatter change detection.',
    },
  ],

  // ── Wildfire · Uttarakhand 2024 ──────────────────────────────────────────
  wildfire: [
    {
      keywords: ['nainital', 'show nainital', 'zoom', 'go to', 'navigate'],
      reply: 'Nainital is the highest priority zone with a score of 0.88. It has 42,300 people affected and 2 hospitals near the fire perimeter. 58% of roads remain passable.',
      mapAction: { action: 'ZOOM', target: 'Nainital' },
    },
    {
      keywords: ['almora'],
      reply: 'Almora is ranked 2nd with a priority score of 0.74. 28,100 people are in the evacuation zone and 1 hospital is near the fire perimeter.',
      mapAction: { action: 'ZOOM', target: 'Almora' },
    },
    {
      keywords: ['pauri', 'garhwal'],
      reply: 'Pauri Garhwal is ranked 3rd with a priority score of 0.61. Road accessibility is 70% — the best of the three zones.',
      mapAction: { action: 'ZOOM', target: 'Pauri Garhwal' },
    },
    {
      keywords: ['hospital', 'hospitals', 'perimeter', 'near', 'medical'],
      reply: 'Nainital has 2 hospitals near the fire perimeter and Almora has 1. Both are at risk if the fire line advances. Hospital layer highlighted.',
      mapAction: { action: 'HIGHLIGHT', layer: 'hospitals' },
    },
    {
      keywords: ['village', 'villages', 'fire path', 'direct'],
      reply: 'Nainital has the largest population in the direct fire path at 42,300, followed by Almora at 28,100. Immediate evacuation of settlements within 5 km of the active fire line is recommended.',
    },
    {
      keywords: ['road', 'roads', 'blocked', 'access'],
      reply: 'Nainital has 3 roads blocked by fire activity and 58% road accessibility. Almora has 2 roads blocked at 63% accessibility.',
      mapAction: { action: 'HIGHLIGHT', layer: 'roads' },
    },
    {
      keywords: ['evacuate', 'evacuation', 'order', 'draft', 'advisory', 'write'],
      reply: 'EVACUATION ORDER — NAINITAL ZONE: Active wildfire confirmed via Sentinel-2 SWIR NBR analysis (05 May 2024). Priority score 0.88. All residents within 5 km of the active fire perimeter must evacuate immediately via NH-109. Report to Haldwani relief camps.',
    },
    {
      keywords: ['highest', 'priority', 'first', 'worst', 'critical'],
      reply: 'Nainital is the highest priority zone with score 0.88. It has the most people in the evacuation zone (42,300), 3 roads blocked, and 2 hospitals near the fire perimeter.',
    },
    {
      keywords: ['confidence', 'accurate', 'detection'],
      reply: 'Average detection confidence across 3 wildfire zones is 72%. Nainital is highest at 76%, Pauri Garhwal lowest at 69%. All figures derived from Sentinel-2 Normalised Burn Ratio analysis.',
    },
  ],

  // ── Landslide · Himachal Pradesh 2023 ────────────────────────────────────
  landslide: [
    {
      keywords: ['shimla', 'show shimla', 'zoom', 'go to', 'navigate'],
      reply: 'Shimla is the highest priority zone with a score of 0.91. Only 34% of roads remain passable — the worst of all landslide-affected zones. 3 hospitals are in the impact zone.',
      mapAction: { action: 'ZOOM', target: 'Shimla' },
    },
    {
      keywords: ['kullu'],
      reply: 'Kullu is ranked 2nd with a priority score of 0.79. Road accessibility is 47% and 4 bridges are at risk.',
      mapAction: { action: 'ZOOM', target: 'Kullu' },
    },
    {
      keywords: ['mandi'],
      reply: 'Mandi is ranked 3rd with a priority score of 0.55. Road accessibility is 61% — the best of the three zones.',
      mapAction: { action: 'ZOOM', target: 'Mandi' },
    },
    {
      keywords: ['road', 'roads', 'blocked', 'debris', 'access'],
      reply: 'Shimla has the worst road accessibility at 34% — meaning 66% of roads are blocked by landslide debris. Kullu follows at 47% blocked.',
      mapAction: { action: 'HIGHLIGHT', layer: 'roads' },
    },
    {
      keywords: ['bridge', 'bridges', 'risk'],
      reply: 'Kullu has 4 bridges at risk — the most of any zone. Shimla has 5 and Mandi has 2. Bridge layer highlighted.',
      mapAction: { action: 'HIGHLIGHT', layer: 'bridges' },
    },
    {
      keywords: ['rescue', 'route', 'accessible', 'least'],
      reply: 'Shimla has the least accessible rescue routes at 34% road passability. Both Shimla and Kullu require alternative approach via air assets.',
    },
    {
      keywords: ['draft', 'advisory', 'closure', 'order', 'write'],
      reply: 'ROAD CLOSURE ADVISORY — SHIMLA AND KULLU DISTRICTS: Landslide debris confirmed via Sentinel-1 InSAR analysis (14 August 2023). NH-5 and NH-21 are impassable. All non-emergency vehicles must use alternate routes. Aerial evacuation has been arranged for isolated settlements.',
    },
    {
      keywords: ['hospital', 'hospitals', 'medical'],
      reply: 'Shimla has 3 hospitals in the landslide impact zone, Kullu has 2, and Mandi has 1. Hospital access is most critical in Shimla given 34% road passability.',
      mapAction: { action: 'HIGHLIGHT', layer: 'hospitals' },
    },
  ],

  // ── Cyclone · Odisha 2023 ────────────────────────────────────────────────
  cyclone: [
    {
      keywords: ['puri', 'show puri', 'zoom', 'go to', 'navigate'],
      reply: 'Puri is the highest priority zone with a score of 0.93. Storm surge estimate is 2.1 m and only 42% of roads remain passable. 7 hospitals are in the impact zone.',
      mapAction: { action: 'ZOOM', target: 'Puri' },
    },
    {
      keywords: ['ganjam'],
      reply: 'Ganjam is ranked 2nd with a priority score of 0.85 and the largest affected population at 318,700. Storm surge estimate is 1.4 m.',
      mapAction: { action: 'ZOOM', target: 'Ganjam' },
    },
    {
      keywords: ['khordha'],
      reply: 'Khordha is ranked 3rd with a priority score of 0.66. Storm surge estimate is 0.8 m and road accessibility is 64%.',
      mapAction: { action: 'ZOOM', target: 'Khordha' },
    },
    {
      keywords: ['village', 'villages', 'coastal', 'evacuate', 'evacuation'],
      reply: 'Puri coastal villages need immediate evacuation — storm surge of 2.1 m is predicted. Ganjam follows with 1.4 m surge risk affecting 318,700 people.',
    },
    {
      keywords: ['storm surge', 'surge', 'flood risk', 'water'],
      reply: 'Puri faces the highest storm surge at 2.1 m, Ganjam 1.4 m, and Khordha 0.8 m. All coastal settlements below 3 m elevation in Puri and Ganjam must evacuate immediately.',
    },
    {
      keywords: ['hospital', 'hospitals', 'medical'],
      reply: 'Ganjam has the most hospitals in the impact zone at 9, followed by Puri with 7 and Khordha with 5. Hospital access in Puri is critical at only 42% road passability.',
      mapAction: { action: 'HIGHLIGHT', layer: 'hospitals' },
    },
    {
      keywords: ['draft', 'advisory', 'order', 'write', 'alert'],
      reply: 'COASTAL EVACUATION ADVISORY — PURI DISTRICT: Cyclone landfall imminent. INSAT-3D Dvorak analysis confirms Category 3 intensity. Storm surge of 2.1 m expected. All residents below 5 m elevation must evacuate immediately to designated cyclone shelters on higher ground.',
    },
    {
      keywords: ['highest', 'priority', 'worst', 'critical', 'first'],
      reply: 'Puri is the highest priority zone with score 0.93 — storm surge 2.1 m, 42% roads passable, and 251,000 people affected. Evacuation must begin immediately.',
    },
  ],

  // ── Earthquake · Gujarat 2024 ────────────────────────────────────────────
  earthquake: [
    {
      keywords: ['kachchh', 'kutch', 'zoom', 'go to', 'navigate'],
      reply: 'Kachchh is the highest priority zone with a score of 0.90. Peak ground acceleration is 0.38g and only 40% of roads remain passable. 4 hospitals are in the impact zone.',
      mapAction: { action: 'ZOOM', target: 'Kachchh' },
    },
    {
      keywords: ['morbi'],
      reply: 'Morbi is ranked 2nd with a priority score of 0.68. Peak ground acceleration is 0.21g and road accessibility is 57%.',
      mapAction: { action: 'ZOOM', target: 'Morbi' },
    },
    {
      keywords: ['jamnagar'],
      reply: 'Jamnagar is ranked 3rd with a priority score of 0.49. Peak ground acceleration is 0.14g — the lowest of the three zones.',
      mapAction: { action: 'ZOOM', target: 'Jamnagar' },
    },
    {
      keywords: ['hospital', 'hospitals', 'structural', 'risk', 'medical'],
      reply: 'Kachchh has 4 hospitals in the impact zone at 0.38g PGA — all at structural risk. Morbi has 2 at 0.21g. Immediate structural assessment is required.',
      mapAction: { action: 'HIGHLIGHT', layer: 'hospitals' },
    },
    {
      keywords: ['building', 'damage', 'concentration', 'collapse'],
      reply: 'The highest building damage concentration is in Kachchh with 0.38g peak ground acceleration affecting 97,800 people. Morbi follows at 0.21g with 54,200 affected.',
    },
    {
      keywords: ['road', 'roads', 'access', 'passable'],
      reply: 'Kachchh has the worst road accessibility at 40%, followed by Morbi at 57%. Both require additional logistics support for emergency vehicle access.',
      mapAction: { action: 'HIGHLIGHT', layer: 'roads' },
    },
    {
      keywords: ['draft', 'advisory', 'shelter', 'order', 'write', 'alert'],
      reply: 'EMERGENCY SHELTER ADVISORY — KACHCHH DISTRICT: Earthquake (M6.2) confirmed via D-InSAR co-seismic displacement analysis (21 March 2024). PGA 0.38g recorded. All residents must vacate structurally damaged buildings immediately. Report to designated shelter centres. Do not re-enter buildings without structural clearance.',
    },
    {
      keywords: ['highest', 'priority', 'worst', 'critical', 'first'],
      reply: 'Kachchh is the highest priority zone with score 0.90 — PGA 0.38g, 40% roads passable, 6 bridges at risk, and 4 hospitals needing structural assessment.',
    },
    {
      keywords: ['confidence', 'accurate', 'detection'],
      reply: 'Average detection confidence across 3 earthquake zones is 77%. Kachchh is highest at 82%, Jamnagar lowest at 71%. All figures derived from Sentinel-1 D-InSAR co-seismic displacement stack.',
    },
  ],
};

/** Fallback responses used when the disaster type has no keyed table. */
const _FALLBACK_RESPONSES = _MOCK_RESPONSES_BY_DISASTER['flood'];

function _getMockCopilotReply(
  message: string,
  disasterType: string,
): { reply: string; map_action: MapAction | null } {
  const lower = message.toLowerCase();
  const table = _MOCK_RESPONSES_BY_DISASTER[disasterType] ?? _FALLBACK_RESPONSES;

  const match = table.find((r) =>
    r.keywords.some((kw) => lower.includes(kw)),
  );
  if (match) return { reply: match.reply, map_action: match.mapAction ?? null };

  // Provide a contextual fallback hint per disaster type
  const hints: Record<string, string> = {
    flood:      'Try asking about specific districts (Idukki, Alappuzha), road access, hospitals, or rescue priorities.',
    wildfire:   'Try asking about villages in the fire path, hospitals near the perimeter, or an evacuation order.',
    landslide:  'Try asking about blocked roads, bridge damage, or accessible rescue routes.',
    cyclone:    'Try asking about storm surge risk, coastal villages, or hospital access.',
    earthquake: 'Try asking about structural risk, building damage, or shelter advisories.',
  };
  return {
    reply: `That information is not in the current analysis data. ${hints[disasterType] ?? 'Try asking about priority zones or infrastructure access.'}`,
    map_action: null,
  };
}

/**
 * POST /api/chat
 * Sends a question to the EO Copilot. Returns a grounded reply
 * and an optional map action command.
 *
 * DEMO_MODE → keyword-matched mock reply after 1.2–2.5 s simulated delay.
 * Timeout  → returns a human-readable timeout message, never throws.
 * Error    → returns a human-readable error message, never throws.
 */
export async function sendCopilotMessage(payload: {
  message: string;
  event_id: string;
  disaster_type: string;
  active_zone: string | null;
}): Promise<{ reply: string; map_action: MapAction | null }> {
  if (DEMO_MODE) {
    // Consistent 1.4 s delay — feels responsive without being instant
    return mockDelay(_getMockCopilotReply(payload.message, payload.disaster_type), 1400);
  }
  try {
    const { data } = await http.post<{ reply: string; map_action: MapAction | null }>(
      '/api/chat',
      payload,
      { timeout: 15_000 },
    );
    return { reply: data.reply, map_action: data.map_action ?? null };
  } catch (err) {
    const isTimeout = (err as AxiosError).code === 'ECONNABORTED';
    console.warn('[OrbitalMind] Copilot API error:', err);
    return {
      reply: isTimeout
        ? 'Response timed out. Please try again.'
        : 'Could not reach the backend. Check that the server is running.',
      map_action: null,
    };
  }
}

/** Default suggestion chips by disaster type (used as fallback). */
const _MOCK_SUGGESTIONS: Record<string, string[]> = {
  flood:      ['Which district should receive rescue boats first?', 'How many hospitals have lost road access?', 'Draft an emergency alert for the highest priority zone.'],
  wildfire:   ['Which villages are in the direct fire path?', 'Which hospitals are near the fire perimeter?', 'Draft an evacuation order for the highest risk zone.'],
  landslide:  ['Which roads are completely blocked by debris?', 'Which areas have the least accessible rescue routes?', 'Draft a road closure advisory for the affected districts.'],
  cyclone:    ['Which coastal villages need immediate evacuation?', 'What is the storm surge risk for the highest ranked zone?', 'Draft a coastal evacuation advisory.'],
  earthquake: ['Which hospitals are structurally at risk?', 'Where is the highest concentration of building damage?', 'Draft an emergency shelter advisory for the affected zones.'],
};

/**
 * GET /api/chat/suggestions?disaster_type=<type>
 * Returns 3 operational prompt chips for the active disaster module.
 * Always returns exactly 3 items — falls back to flood if type unknown.
 */
export async function getCopilotSuggestions(
  disasterType: string,
): Promise<CopilotSuggestions> {
  if (DEMO_MODE) {
    return mockDelay(
      {
        suggestions: _MOCK_SUGGESTIONS[disasterType] ?? _MOCK_SUGGESTIONS['flood'],
        disaster_type: disasterType,
      },
      150,
    );
  }
  try {
    const { data } = await http.get<CopilotSuggestions>('/api/chat/suggestions', {
      params: { disaster_type: disasterType },
    });
    return data;
  } catch (err) {
    console.warn('[OrbitalMind] Suggestions API error:', err);
    return {
      suggestions: _MOCK_SUGGESTIONS[disasterType] ?? _MOCK_SUGGESTIONS['flood'],
      disaster_type: disasterType,
    };
  }
}

