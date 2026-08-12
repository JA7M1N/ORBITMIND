import { useEffect, useRef } from 'react';
import * as maplibregl from 'maplibre-gl';
import type { InfraPoint } from '../mock/mockData';
import './MapView.css';

const HOSPITAL_SVG = `
<svg viewBox="0 0 20 20" xmlns="http://www.w3.org/2000/svg">
  <circle cx="10" cy="10" r="9" fill="#ffffff" stroke="#dc2626" stroke-width="1.5"/>
  <path d="M10 5.5v9M5.5 10h9" stroke="#dc2626" stroke-width="2.2" stroke-linecap="round"/>
</svg>`;

const SCHOOL_SVG = `
<svg viewBox="0 0 18 18" xmlns="http://www.w3.org/2000/svg">
  <circle cx="9" cy="9" r="8" fill="#ffffff" stroke="#1e40af" stroke-width="1.5"/>
  <text x="9" y="12.5" font-family="Inter, sans-serif" font-size="9" font-weight="700" fill="#1e40af" text-anchor="middle">S</text>
</svg>`;

interface InfraMarkerLayerProps {
  map: maplibregl.Map | null;
  points: InfraPoint[];
  showHospitals: boolean;
  showSchools: boolean;
  /** Markers are only meaningful once a flood event with real geography
   * is loaded — parent gates this rather than the layer guessing. */
  visible: boolean;
}

export default function InfraMarkerLayer({
  map,
  points,
  showHospitals,
  showSchools,
  visible,
}: InfraMarkerLayerProps) {
  const markersRef = useRef<Map<string, maplibregl.Marker>>(new Map());

  // Build (or tear down) the full marker set once per map/points/visible
  // change. Toggle + viewport culling below just show/hide these — no
  // need to recreate DOM nodes on every pan.
  useEffect(() => {
    if (!map) return;

    if (!visible) {
      markersRef.current.forEach((m) => m.remove());
      markersRef.current.clear();
      return;
    }

    for (const point of points) {
      if (markersRef.current.has(point.id)) continue;
      const el = document.createElement('div');
      el.className = `infra-marker infra-marker--${point.kind}`;
      el.innerHTML = point.kind === 'hospital' ? HOSPITAL_SVG : SCHOOL_SVG;
      el.title = point.name;
      const marker = new maplibregl.Marker({ element: el }).setLngLat(point.coordinates);
      markersRef.current.set(point.id, marker);
    }

    // Drop markers for points no longer in the list (e.g. data refresh).
    const validIds = new Set(points.map((p) => p.id));
    markersRef.current.forEach((marker, id) => {
      if (!validIds.has(id)) {
        marker.remove();
        markersRef.current.delete(id);
      }
    });

    return () => {
      markersRef.current.forEach((m) => m.remove());
      markersRef.current.clear();
    };
  }, [map, points, visible]);

  // Viewport culling + type toggles: with hundreds/thousands of real
  // facility records from the backend, adding every marker to the map
  // regardless of what's on screen would tank pan/zoom performance.
  // Only markers inside the current bounds — and whose type toggle is
  // on — get attached to the map at all.
  useEffect(() => {
    if (!map || !visible) return;

    function sync() {
      const bounds = map!.getBounds();
      for (const point of points) {
        const marker = markersRef.current.get(point.id);
        if (!marker) continue;
        const typeEnabled = point.kind === 'hospital' ? showHospitals : showSchools;
        const inView = bounds.contains(point.coordinates);
        const shouldShow = typeEnabled && inView;
        const isAttached = marker.getElement().isConnected;
        if (shouldShow && !isAttached) marker.addTo(map!);
        if (!shouldShow && isAttached) marker.remove();
      }
    }

    sync();
    map.on('moveend', sync);
    return () => {
      map.off('moveend', sync);
    };
  }, [map, points, showHospitals, showSchools, visible]);

  return null;
}
