import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react';
import * as maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import type { DisasterModule } from '../types';
import './MapView.css';

/**
 * A raster-only style pointed at OSM's tile server. Kept intentionally
 * minimal (one source, one layer) — every other visual layer (zones,
 * infra markers) is added by sibling components once `onReady` fires,
 * layered on top of this base rather than baked into the style.
 */
const OSM_STYLE: maplibregl.StyleSpecification = {
  version: 8,
  sources: {
    osm: {
      type: 'raster',
      tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
      tileSize: 256,
      attribution: '&copy; OpenStreetMap contributors',
    },
  },
  layers: [{ id: 'osm-base', type: 'raster', source: 'osm', minzoom: 0, maxzoom: 19 }],
};

function easeInOutCubic(t: number): number {
  return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
}

interface MapViewProps {
  activeModule: DisasterModule;
  /** Fired once with the live map instance after style load, so sibling
   * layer components (AffectedZoneLayer, InfraMarkerLayer) know when
   * it's safe to add sources/layers. */
  onReady?: (map: maplibregl.Map) => void;
}

const MapView = forwardRef<maplibregl.Map, MapViewProps>(
  ({ activeModule, onReady }, ref) => {
    const containerRef = useRef<HTMLDivElement>(null);
    const mapRef = useRef<maplibregl.Map | null>(null);
    const [ready, setReady] = useState(false);

    useImperativeHandle(ref, () => mapRef.current as maplibregl.Map, [ready]);

    // Initialize map once — starts on a wide, dark India view rather than
    // snapping straight to the active module, so the first frame reads
    // as "the whole operating theater," then flyTo narrows it below.
    useEffect(() => {
      if (!containerRef.current || mapRef.current) return;

      const map = new maplibregl.Map({
        container: containerRef.current,
        style: OSM_STYLE,
        center: [78, 22],
        zoom: 5,
        attributionControl: { compact: true },
      });

      map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'bottom-right');

      map.on('load', () => {
        mapRef.current = map;
        setReady(true);
        onReady?.(map);
        map.flyTo({
          center: activeModule.mapCenter,
          zoom: activeModule.mapZoom,
          duration: 1400,
          easing: easeInOutCubic,
        });
      });

      // The right panel opening/closing (or any container resize) leaves
      // MapLibre's internal canvas size stale until told otherwise —
      // without this the map renders into the wrong viewport and tiles
      // clip at the old edge.
      const resizeObserver = new ResizeObserver(() => {
        mapRef.current?.resize();
      });
      resizeObserver.observe(containerRef.current);

      return () => {
        resizeObserver.disconnect();
        map.remove();
        mapRef.current = null;
        setReady(false);
      };
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    // Fly to the active module's region whenever it changes.
    useEffect(() => {
      if (!ready || !mapRef.current) return;
      mapRef.current.flyTo({
        center: activeModule.mapCenter,
        zoom: activeModule.mapZoom,
        duration: 1400,
        easing: easeInOutCubic,
      });
    }, [ready, activeModule.mapCenter, activeModule.mapZoom]);

    return (
      <div className="map-view-container">
        <div ref={containerRef} className="map-view map-view--filtered" data-accent-transition />
      </div>
    );
  },
);

MapView.displayName = 'MapView';
export default MapView;
