import { useEffect, useRef } from 'react';
import * as maplibregl from 'maplibre-gl';
import type { MapLayerMouseEvent } from 'maplibre-gl';
import type { DisasterType, PriorityZoneCollection } from '../types';
import { getDisasterColor } from '../utils/disasterColors';
import { polygonCentroid, scalePolygon } from '../utils/geo';
import './MapView.css';

const SOURCE_ID = 'affected-zones';
const GLOW_SOURCE_ID = 'affected-zones-glow';
const FILL_LAYER = 'affected-zones-fill';
const OUTLINE_LAYER = 'affected-zones-outline';
const GLOW_LAYER = 'affected-zones-glow-fill';
const SELECTED_OUTLINE_LAYER = 'affected-zones-selected-outline';

interface AffectedZoneLayerProps {
  map: maplibregl.Map | null;
  geojson: PriorityZoneCollection;
  disasterType: DisasterType;
  selectedZoneId: string | null;
  onZoneClick: (zoneId: string) => void;
  /** 0–1 multiplier over the base fill/outline opacity, driven by
   * BeforeAfterToggle (pre-disaster = 0, post-disaster = 1) and by the
   * disaster-switch orchestration's fade-out step. Layered on top of
   * the existing hover opacity rather than replacing it, so hover
   * highlighting keeps working once the layer is visible again. */
  opacityMultiplier?: number;
}

/** Empty collection used to clear the glow source when nothing is selected. */
const EMPTY_FC: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features: [] };

export default function AffectedZoneLayer({
  map,
  geojson,
  disasterType,
  selectedZoneId,
  onZoneClick,
  opacityMultiplier = 1,
}: AffectedZoneLayerProps) {
  const hoveredIdRef = useRef<string | null>(null);
  const showTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const hideTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const popupRef = useRef<maplibregl.Popup | null>(null);
  const onZoneClickRef = useRef(onZoneClick);
  onZoneClickRef.current = onZoneClick;

  // Mount layers once per map instance; tear them all down on unmount so
  // switching disaster modules never leaves a stale source/layer behind.
  useEffect(() => {
    if (!map) return;

    const fillColor = getDisasterColor(disasterType, 'fill');
    const outlineColor = getDisasterColor(disasterType, 'outline');

    map.addSource(SOURCE_ID, {
      type: 'geojson',
      data: geojson as unknown as GeoJSON.FeatureCollection,
      promoteId: 'zoneId',
    });
    map.addSource(GLOW_SOURCE_ID, { type: 'geojson', data: EMPTY_FC });

    // The `*-opacity-transition` lets MapLibre itself animate opacity
    // changes over 500ms — this is what drives both the disaster-switch
    // fade-out and the BeforeAfterToggle's 0→0.55 crossfade smoothly,
    // without hand-rolled requestAnimationFrame code.
    map.addLayer({
      id: FILL_LAYER,
      type: 'fill',
      source: SOURCE_ID,
      paint: {
        'fill-color': fillColor,
        'fill-opacity': [
          '*',
          opacityMultiplier,
          ['case', ['boolean', ['feature-state', 'hover'], false], 0.75, 0.55],
        ],
        'fill-opacity-transition': { duration: 500, delay: 0 },
      },
    });

    map.addLayer({
      id: OUTLINE_LAYER,
      type: 'line',
      source: SOURCE_ID,
      paint: {
        'line-color': outlineColor,
        'line-width': 2,
        'line-opacity': opacityMultiplier,
        'line-opacity-transition': { duration: 500, delay: 0 },
      },
    });

    // Glow sits visually beneath the outline but is added after fill so
    // it doesn't get occluded by it; z-order is fixed with moveLayer below.
    map.addLayer({
      id: GLOW_LAYER,
      type: 'fill',
      source: GLOW_SOURCE_ID,
      paint: { 'fill-color': '#fbbf24', 'fill-opacity': 0.15 },
    });
    map.moveLayer(GLOW_LAYER, FILL_LAYER);

    map.addLayer({
      id: SELECTED_OUTLINE_LAYER,
      type: 'line',
      source: SOURCE_ID,
      paint: { 'line-color': '#fbbf24', 'line-width': 3 },
      filter: ['==', ['get', 'zoneId'], '__none__'],
    });

    const popup = new maplibregl.Popup({
      closeButton: false,
      closeOnClick: false,
      offset: 14,
      className: 'zone-tooltip',
    });
    popupRef.current = popup;

    function clearHover() {
      if (hoveredIdRef.current !== null) {
        map!.setFeatureState({ source: SOURCE_ID, id: hoveredIdRef.current }, { hover: false });
        hoveredIdRef.current = null;
      }
    }

    function handleMouseMove(e: MapLayerMouseEvent) {
      const feature = e.features?.[0];
      if (!feature) return;
      const zoneId = feature.properties?.zoneId as string;
      const props = feature.properties as Record<string, unknown>;

      if (hoveredIdRef.current !== zoneId) {
        clearHover();
        hoveredIdRef.current = zoneId;
        map!.setFeatureState({ source: SOURCE_ID, id: zoneId }, { hover: true });
        map!.getCanvas().style.cursor = 'pointer';
      }

      if (hideTimerRef.current) {
        clearTimeout(hideTimerRef.current);
        hideTimerRef.current = null;
      }

      // 150ms debounce: an instant tooltip fires on every pixel the
      // cursor crosses while scanning the map, which reads as jittery.
      // Waiting a beat makes it feel like the map noticed you stopped,
      // not that it's reacting to every movement.
      if (showTimerRef.current) clearTimeout(showTimerRef.current);
      showTimerRef.current = setTimeout(() => {
        popup
          .setLngLat(e.lngLat)
          .setHTML(
            `<div class="zone-tooltip-pill">
              <span class="zone-tooltip-pill__name">${props.zoneName}</span>
              <span class="zone-tooltip-pill__meta">
                <span>Rank <span class="font-mono">#${props.priorityRank}</span></span>
                <span>Confidence <span class="font-mono">${Math.round((props.confidence as number) * 100)}%</span></span>
              </span>
            </div>`,
          )
          .addTo(map!);
      }, 150);
    }

    function handleMouseLeave() {
      if (showTimerRef.current) {
        clearTimeout(showTimerRef.current);
        showTimerRef.current = null;
      }
      clearHover();
      map!.getCanvas().style.cursor = '';

      // 100ms grace period before the tooltip actually disappears — an
      // instant close on mouseleave feels like it's being yanked away.
      if (hideTimerRef.current) clearTimeout(hideTimerRef.current);
      hideTimerRef.current = setTimeout(() => popup.remove(), 100);
    }

    function handleClick(e: MapLayerMouseEvent) {
      const feature = e.features?.[0];
      if (!feature) return;
      const zoneId = feature.properties?.zoneId as string;
      onZoneClickRef.current(zoneId);
    }

    map.on('mousemove', FILL_LAYER, handleMouseMove);
    map.on('mouseleave', FILL_LAYER, handleMouseLeave);
    map.on('click', FILL_LAYER, handleClick);

    return () => {
      map.off('mousemove', FILL_LAYER, handleMouseMove);
      map.off('mouseleave', FILL_LAYER, handleMouseLeave);
      map.off('click', FILL_LAYER, handleClick);
      if (showTimerRef.current) clearTimeout(showTimerRef.current);
      if (hideTimerRef.current) clearTimeout(hideTimerRef.current);
      popup.remove();

      for (const id of [SELECTED_OUTLINE_LAYER, GLOW_LAYER, OUTLINE_LAYER, FILL_LAYER]) {
        if (map.getLayer(id)) map.removeLayer(id);
      }
      for (const id of [GLOW_SOURCE_ID, SOURCE_ID]) {
        if (map.getSource(id)) map.removeSource(id);
      }
    };
    // Re-run this whole setup when the map instance itself changes
    // (mount/unmount); data/color/selection updates are handled by the
    // lighter-weight effects below instead of a full teardown.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map]);

  // Keep the source data current as zones load/change.
  useEffect(() => {
    if (!map || !map.getSource(SOURCE_ID)) return;
    (map.getSource(SOURCE_ID) as maplibregl.GeoJSONSource).setData(
      geojson as unknown as GeoJSON.FeatureCollection,
    );
  }, [map, geojson]);

  // Repaint fill/outline colors when the active disaster changes.
  useEffect(() => {
    if (!map || !map.getLayer(FILL_LAYER)) return;
    map.setPaintProperty(FILL_LAYER, 'fill-color', getDisasterColor(disasterType, 'fill'));
    map.setPaintProperty(OUTLINE_LAYER, 'line-color', getDisasterColor(disasterType, 'outline'));
  }, [map, disasterType]);

  // Crossfade the whole layer's opacity — driven by BeforeAfterToggle
  // and by the disaster-switch orchestration's fade-out step. The
  // layer stays mounted (sources/listeners intact); only opacity moves.
  useEffect(() => {
    if (!map || !map.getLayer(FILL_LAYER)) return;
    map.setPaintProperty(FILL_LAYER, 'fill-opacity', [
      '*',
      opacityMultiplier,
      ['case', ['boolean', ['feature-state', 'hover'], false], 0.75, 0.55],
    ]);
    map.setPaintProperty(OUTLINE_LAYER, 'line-opacity', opacityMultiplier);
  }, [map, opacityMultiplier]);

  // Drive the selected-zone outline filter and the glow geometry.
  useEffect(() => {
    if (!map || !map.getLayer(SELECTED_OUTLINE_LAYER)) return;
    map.setFilter(SELECTED_OUTLINE_LAYER, ['==', ['get', 'zoneId'], selectedZoneId ?? '__none__']);

    const glowSource = map.getSource(GLOW_SOURCE_ID) as maplibregl.GeoJSONSource | undefined;
    if (!glowSource) return;

    const selectedFeature = geojson.features.find((f) => f.properties.zoneId === selectedZoneId);
    if (!selectedFeature || selectedFeature.geometry.type !== 'Polygon') {
      glowSource.setData(EMPTY_FC);
      return;
    }
    const glowPolygon = scalePolygon(selectedFeature.geometry as GeoJSON.Polygon, 1.35);
    glowSource.setData({
      type: 'FeatureCollection',
      features: [{ type: 'Feature', geometry: glowPolygon, properties: {} }],
    });
  }, [map, geojson, selectedZoneId]);

  // Selecting a zone re-centers and zooms in slightly — a color change
  // alone reads as "highlighted," the camera move reads as "chosen."
  useEffect(() => {
    if (!map || !selectedZoneId) return;
    const feature = geojson.features.find((f) => f.properties.zoneId === selectedZoneId);
    if (!feature || feature.geometry.type !== 'Polygon') return;
    const center = polygonCentroid(feature.geometry as GeoJSON.Polygon);
    map.easeTo({ center, zoom: map.getZoom() + 0.3, duration: 600 });
    // Intentionally excludes `map.getZoom()` from deps — re-running this
    // on every zoom change (including the one it causes) would loop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, selectedZoneId]);

  return null;
}
