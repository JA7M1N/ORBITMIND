/**
 * Mock data — stands in for the live API until backend integration
 * (Day 1 evening). Shapes match the real endpoints exactly so swapping
 * a mock import for an axios call is the only change needed later.
 *
 * Flood/Kerala numbers are grounded in real 2011 census district
 * populations and real district names, scaled to plausible
 * "affected" subsets for the 2018 flood event. The other four modules
 * are demo-mode and use realistic but illustrative figures, still tied
 * to their real event's real districts/regions.
 *
 * Zone geometry: the real backend sends actual boundary polygons. Until
 * integration we only have a center point per zone, so `circlePolygon`
 * synthesizes a soft blob sized by priority score — never presented as
 * a real administrative boundary, just enough for the fill/outline
 * layers to render against.
 */

import { circlePolygon } from '../utils/geo';
import type {
  DisasterModule,
  DisasterEvent,
  DisasterType,
  PriorityZone,
  PriorityZoneCollection,
  NarrationResponse,
} from '../types';

export const MOCK_MODULES: DisasterModule[] = [
  {
    type: 'flood',
    displayName: 'Flood',
    status: 'live',
    regionLabel: 'Kerala · 2018',
    mapCenter: [76.5, 10.5],
    mapZoom: 8,
  },
  {
    type: 'wildfire',
    displayName: 'Wildfire',
    status: 'demo',
    regionLabel: 'Uttarakhand · 2024',
    mapCenter: [79.5, 30.5],
    mapZoom: 9,
  },
  {
    type: 'landslide',
    displayName: 'Landslide',
    status: 'demo',
    regionLabel: 'Himachal Pradesh · 2023',
    mapCenter: [77.2, 31.8],
    mapZoom: 9,
  },
  {
    type: 'cyclone',
    displayName: 'Cyclone',
    status: 'demo',
    regionLabel: 'Odisha · 2023',
    mapCenter: [85.8, 20.0],
    mapZoom: 8,
  },
  {
    type: 'earthquake',
    displayName: 'Earthquake',
    status: 'demo',
    regionLabel: 'Gujarat · 2024',
    mapCenter: [71.5, 22.5],
    mapZoom: 9,
  },
];

export const MOCK_EVENTS: DisasterEvent[] = [
  {
    eventId: 'evt-flood-kerala-2018',
    disasterType: 'flood',
    name: 'Kerala Floods 2018',
    date: '2018-08-08',
    summary:
      'Severe monsoon flooding across 13 of 14 districts following the highest August rainfall in nearly a century.',
  },
  {
    eventId: 'evt-wildfire-uttarakhand-2024',
    disasterType: 'wildfire',
    name: 'Uttarakhand Forest Fires 2024',
    date: '2024-05-02',
    summary:
      'Widespread forest fires across Nainital, Almora, and Pauri Garhwal during an unusually dry pre-monsoon season.',
  },
  {
    eventId: 'evt-landslide-himachal-2023',
    disasterType: 'landslide',
    name: 'Himachal Pradesh Landslides 2023',
    date: '2023-08-14',
    summary:
      'Monsoon-triggered landslides across Shimla and Kullu districts following days of continuous heavy rainfall.',
  },
  {
    eventId: 'evt-cyclone-odisha-2023',
    disasterType: 'cyclone',
    name: 'Cyclone Odisha 2023',
    date: '2023-05-11',
    summary:
      'Severe cyclonic storm making landfall on the Odisha coast, affecting Puri, Ganjam, and Khordha districts.',
  },
  {
    eventId: 'evt-earthquake-gujarat-2024',
    disasterType: 'earthquake',
    name: 'Gujarat Earthquake 2024',
    date: '2024-03-21',
    summary:
      'Moderate-magnitude earthquake centered near Kachchh, with damage reported across the Rann region.',
  },
];

/** Raw fixture shape before geometry synthesis — center point + properties. */
interface ZoneFixture {
  center: [number, number];
  properties: PriorityZone;
}

function buildZoneCollection(fixtures: ZoneFixture[]): PriorityZoneCollection {
  return {
    type: 'FeatureCollection',
    features: fixtures.map((f) => ({
      type: 'Feature',
      // Radius scales with priority so the most urgent zone also reads
      // as the largest shape on the map, before anyone reads a number.
      geometry: circlePolygon(f.center, 0.05 + f.properties.priorityScore * 0.045),
      properties: f.properties,
    })),
  };
}

/**
 * Kerala 2018 flood priority zones. District populations are drawn from
 * the 2011 census; population_affected is a scaled estimate of the
 * flood-affected subset, not the full district population.
 */
const FLOOD_FIXTURES: ZoneFixture[] = [
  {
    center: [76.9761, 9.8497],
    properties: {
      zoneId: 'zone-idukki', zoneName: 'Idukki', priorityScore: 0.94, priorityRank: 1,
      populationAffected: 187500, hospitalsAffected: 6, schoolsAffected: 42,
      bridgesAtRisk: 9, roadsIntactPct: 38, confidence: 0.91, disasterType: 'flood',
    },
  },
  {
    center: [76.3388, 9.4981],
    properties: {
      zoneId: 'zone-alappuzha', zoneName: 'Alappuzha', priorityScore: 0.89, priorityRank: 2,
      populationAffected: 412300, hospitalsAffected: 11, schoolsAffected: 68,
      bridgesAtRisk: 5, roadsIntactPct: 45, confidence: 0.88, disasterType: 'flood',
    },
  },
  {
    center: [76.5222, 9.5916],
    properties: {
      zoneId: 'zone-kottayam', zoneName: 'Kottayam', priorityScore: 0.82, priorityRank: 3,
      populationAffected: 298100, hospitalsAffected: 8, schoolsAffected: 51,
      bridgesAtRisk: 4, roadsIntactPct: 52, confidence: 0.86, disasterType: 'flood',
    },
  },
  {
    center: [76.7870, 9.2648],
    properties: {
      zoneId: 'zone-pathanamthitta', zoneName: 'Pathanamthitta', priorityScore: 0.78, priorityRank: 4,
      populationAffected: 176900, hospitalsAffected: 5, schoolsAffected: 33,
      bridgesAtRisk: 7, roadsIntactPct: 41, confidence: 0.83, disasterType: 'flood',
    },
  },
  {
    center: [76.2673, 9.9312],
    properties: {
      zoneId: 'zone-ernakulam', zoneName: 'Ernakulam', priorityScore: 0.71, priorityRank: 5,
      populationAffected: 521400, hospitalsAffected: 14, schoolsAffected: 77,
      bridgesAtRisk: 3, roadsIntactPct: 61, confidence: 0.89, disasterType: 'flood',
    },
  },
  {
    center: [76.2144, 10.5276],
    properties: {
      zoneId: 'zone-thrissur', zoneName: 'Thrissur', priorityScore: 0.64, priorityRank: 6,
      populationAffected: 289600, hospitalsAffected: 9, schoolsAffected: 46,
      bridgesAtRisk: 2, roadsIntactPct: 67, confidence: 0.84, disasterType: 'flood',
    },
  },
  {
    center: [76.6548, 9.7189],
    properties: {
      zoneId: 'zone-wayanad', zoneName: 'Wayanad', priorityScore: 0.58, priorityRank: 7,
      populationAffected: 94200, hospitalsAffected: 3, schoolsAffected: 21,
      bridgesAtRisk: 6, roadsIntactPct: 55, confidence: 0.79, disasterType: 'flood',
    },
  },
  {
    center: [76.0788, 10.8505],
    properties: {
      zoneId: 'zone-malappuram', zoneName: 'Malappuram', priorityScore: 0.47, priorityRank: 8,
      populationAffected: 218700, hospitalsAffected: 7, schoolsAffected: 39,
      bridgesAtRisk: 1, roadsIntactPct: 74, confidence: 0.81, disasterType: 'flood',
    },
  },
];

const WILDFIRE_FIXTURES: ZoneFixture[] = [
  {
    center: [79.4630, 29.3919],
    properties: {
      zoneId: 'zone-nainital', zoneName: 'Nainital', priorityScore: 0.88, priorityRank: 1,
      populationAffected: 42300, hospitalsAffected: 2, schoolsAffected: 14,
      bridgesAtRisk: 0, roadsIntactPct: 58, confidence: 0.76, disasterType: 'wildfire',
    },
  },
  {
    center: [79.6591, 29.5971],
    properties: {
      zoneId: 'zone-almora', zoneName: 'Almora', priorityScore: 0.74, priorityRank: 2,
      populationAffected: 28100, hospitalsAffected: 1, schoolsAffected: 9,
      bridgesAtRisk: 0, roadsIntactPct: 63, confidence: 0.72, disasterType: 'wildfire',
    },
  },
  {
    center: [78.7803, 29.8880],
    properties: {
      zoneId: 'zone-pauri-garhwal', zoneName: 'Pauri Garhwal', priorityScore: 0.61, priorityRank: 3,
      populationAffected: 19700, hospitalsAffected: 1, schoolsAffected: 7,
      bridgesAtRisk: 1, roadsIntactPct: 70, confidence: 0.69, disasterType: 'wildfire',
    },
  },
];

const LANDSLIDE_FIXTURES: ZoneFixture[] = [
  {
    center: [77.1734, 31.1048],
    properties: {
      zoneId: 'zone-shimla', zoneName: 'Shimla', priorityScore: 0.91, priorityRank: 1,
      populationAffected: 63400, hospitalsAffected: 3, schoolsAffected: 18,
      bridgesAtRisk: 5, roadsIntactPct: 34, confidence: 0.85, disasterType: 'landslide',
    },
  },
  {
    center: [77.1095, 31.9576],
    properties: {
      zoneId: 'zone-kullu', zoneName: 'Kullu', priorityScore: 0.79, priorityRank: 2,
      populationAffected: 41200, hospitalsAffected: 2, schoolsAffected: 12,
      bridgesAtRisk: 4, roadsIntactPct: 47, confidence: 0.81, disasterType: 'landslide',
    },
  },
  {
    center: [77.3452, 31.5204],
    properties: {
      zoneId: 'zone-mandi', zoneName: 'Mandi', priorityScore: 0.55, priorityRank: 3,
      populationAffected: 22900, hospitalsAffected: 1, schoolsAffected: 8,
      bridgesAtRisk: 2, roadsIntactPct: 61, confidence: 0.74, disasterType: 'landslide',
    },
  },
];

const CYCLONE_FIXTURES: ZoneFixture[] = [
  {
    center: [85.8312, 19.8135],
    properties: {
      zoneId: 'zone-puri', zoneName: 'Puri', priorityScore: 0.93, priorityRank: 1,
      populationAffected: 251000, hospitalsAffected: 7, schoolsAffected: 34,
      bridgesAtRisk: 3, roadsIntactPct: 42, confidence: 0.88, disasterType: 'cyclone',
    },
  },
  {
    center: [84.9990, 19.3872],
    properties: {
      zoneId: 'zone-ganjam', zoneName: 'Ganjam', priorityScore: 0.85, priorityRank: 2,
      populationAffected: 318700, hospitalsAffected: 9, schoolsAffected: 41,
      bridgesAtRisk: 2, roadsIntactPct: 50, confidence: 0.84, disasterType: 'cyclone',
    },
  },
  {
    center: [85.6134, 20.1301],
    properties: {
      zoneId: 'zone-khordha', zoneName: 'Khordha', priorityScore: 0.66, priorityRank: 3,
      populationAffected: 189400, hospitalsAffected: 5, schoolsAffected: 26,
      bridgesAtRisk: 1, roadsIntactPct: 64, confidence: 0.80, disasterType: 'cyclone',
    },
  },
];

const EARTHQUAKE_FIXTURES: ZoneFixture[] = [
  {
    center: [69.8000, 23.2500],
    properties: {
      zoneId: 'zone-kachchh', zoneName: 'Kachchh', priorityScore: 0.90, priorityRank: 1,
      populationAffected: 97800, hospitalsAffected: 4, schoolsAffected: 19,
      bridgesAtRisk: 6, roadsIntactPct: 40, confidence: 0.82, disasterType: 'earthquake',
    },
  },
  {
    center: [71.6724, 22.3039],
    properties: {
      zoneId: 'zone-morbi', zoneName: 'Morbi', priorityScore: 0.68, priorityRank: 2,
      populationAffected: 54200, hospitalsAffected: 2, schoolsAffected: 11,
      bridgesAtRisk: 3, roadsIntactPct: 57, confidence: 0.77, disasterType: 'earthquake',
    },
  },
  {
    center: [70.7833, 22.4707],
    properties: {
      zoneId: 'zone-jamnagar', zoneName: 'Jamnagar', priorityScore: 0.49, priorityRank: 3,
      populationAffected: 31600, hospitalsAffected: 1, schoolsAffected: 6,
      bridgesAtRisk: 1, roadsIntactPct: 71, confidence: 0.71, disasterType: 'earthquake',
    },
  },
];

export const MOCK_ZONES_BY_DISASTER: Record<DisasterType, PriorityZoneCollection> = {
  flood: buildZoneCollection(FLOOD_FIXTURES),
  wildfire: buildZoneCollection(WILDFIRE_FIXTURES),
  landslide: buildZoneCollection(LANDSLIDE_FIXTURES),
  cyclone: buildZoneCollection(CYCLONE_FIXTURES),
  earthquake: buildZoneCollection(EARTHQUAKE_FIXTURES),
};

/** Kept for any code still importing the flood collection directly. */
export const MOCK_FLOOD_ZONES = MOCK_ZONES_BY_DISASTER.flood;

/**
 * Hospital/school point markers, flood module only (per spec: infra
 * markers only render once a flood event is loaded). Coordinates are
 * illustrative points within each district, not real facility records.
 */
export interface InfraPoint {
  id: string;
  kind: 'hospital' | 'school';
  name: string;
  coordinates: [number, number];
}

export const MOCK_FLOOD_INFRA: InfraPoint[] = [
  { id: 'h-idukki-1', kind: 'hospital', name: 'Idukki District Hospital', coordinates: [76.9550, 9.8560] },
  { id: 'h-idukki-2', kind: 'hospital', name: 'Painavu Taluk Hospital', coordinates: [77.0102, 9.8321] },
  { id: 's-idukki-1', kind: 'school', name: 'GHSS Idukki', coordinates: [76.9890, 9.8410] },
  { id: 'h-alappuzha-1', kind: 'hospital', name: 'Alappuzha Medical College', coordinates: [76.3520, 9.4899] },
  { id: 's-alappuzha-1', kind: 'school', name: 'SD College HSS Alappuzha', coordinates: [76.3290, 9.5040] },
  { id: 's-alappuzha-2', kind: 'school', name: 'St. Michael\u2019s HS', coordinates: [76.3455, 9.4771] },
  { id: 'h-kottayam-1', kind: 'hospital', name: 'Kottayam General Hospital', coordinates: [76.5194, 9.5945] },
  { id: 's-kottayam-1', kind: 'school', name: 'CMS College HSS', coordinates: [76.5266, 9.5875] },
  { id: 'h-ernakulam-1', kind: 'hospital', name: 'Ernakulam General Hospital', coordinates: [76.2820, 9.9720] },
  { id: 'h-ernakulam-2', kind: 'hospital', name: 'Aluva Taluk Hospital', coordinates: [76.3520, 10.1080] },
  { id: 's-ernakulam-1', kind: 'school', name: 'Maharaja\u2019s HSS', coordinates: [76.2841, 9.9752] },
];

export const MOCK_NARRATIONS: Record<string, NarrationResponse> = {
  'zone-idukki': {
    narration:
      'Idukki is the most critical zone in this event. Multiple dam-adjacent settlements remain cut off, with under 40% of road access intact and nine bridges structurally at risk. Six hospitals report disrupted supply routes. Prioritize helicopter-based evacuation and medical resupply here first.',
    cached: false,
  },
  'zone-alappuzha': {
    narration:
      'Alappuzha carries the largest affected population in the event at over 400,000 residents across low-lying backwater areas. Road access is compromised but not severed. Boat-based evacuation and relief distribution should scale quickly given the population density.',
    cached: false,
  },
  'zone-kottayam': {
    narration:
      'Kottayam shows a steep rise in water levels near the Meenachil river basin. With just over half of roads intact and four bridges flagged at risk, relief convoys should be rerouted through the eastern highway corridor to maintain supply continuity.',
    cached: true,
  },
  'zone-puri': {
    narration:
      'Puri took the most direct landfall impact in this event. Coastal wards report the steepest infrastructure damage in the district, with under half of roads passable. Coordinate shelter capacity here before redirecting relief further down the coast.',
    cached: false,
  },
  'zone-shimla': {
    narration:
      'Shimla shows the highest slope-failure density in this event, with five bridges flagged structurally at risk and just over a third of roads passable. Treat as the lead zone for engineering assessment teams before reopening any through-routes.',
    cached: false,
  },
};
