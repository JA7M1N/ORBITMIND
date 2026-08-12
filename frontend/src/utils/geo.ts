/**
 * Geometry helpers.
 *
 * The real backend will send actual district/zone boundary polygons from
 * GET /api/events/{id}/zones. Until integration, mock zones only have a
 * center point, so `circlePolygon` synthesizes a soft rounded-blob
 * polygon around that point — enough for fill/outline layers to render
 * correctly, without pretending to be a real administrative boundary.
 * Any real Polygon/MultiPolygon geometry from the backend flows through
 * AffectedZoneLayer unchanged; nothing downstream assumes circles.
 */

type Ring = [number, number][];

export function circlePolygon(
  center: [number, number],
  radiusDeg: number,
  points = 28,
): GeoJSON.Polygon {
  const [lng, lat] = center;
  const latRad = (lat * Math.PI) / 180;
  const coords: Ring = [];
  for (let i = 0; i <= points; i++) {
    const angle = (i / points) * 2 * Math.PI;
    // Slight irregularity per-vertex (seeded by index) so zones read as
    // organic terrain outlines rather than obviously perfect circles.
    const wobble = 1 + 0.06 * Math.sin(i * 2.7);
    const dx = (radiusDeg * wobble * Math.cos(angle)) / Math.cos(latRad);
    const dy = radiusDeg * wobble * Math.sin(angle);
    coords.push([lng + dx, lat + dy]);
  }
  return { type: 'Polygon', coordinates: [coords] };
}

/** Average of a polygon's outer ring — sufficient for our own generated
 * blobs and for centering flyTo/easeTo on real convex-ish zone polygons. */
export function polygonCentroid(polygon: GeoJSON.Polygon): [number, number] {
  const ring = polygon.coordinates[0];
  let x = 0;
  let y = 0;
  for (const [lng, lat] of ring) {
    x += lng;
    y += lat;
  }
  return [x / ring.length, y / ring.length];
}

/** Scales a polygon outward from its own centroid — used to build the
 * soft "glow" layer behind a selected zone without a second data source. */
export function scalePolygon(
  polygon: GeoJSON.Polygon,
  factor: number,
): GeoJSON.Polygon {
  const [cx, cy] = polygonCentroid(polygon);
  return {
    type: 'Polygon',
    coordinates: polygon.coordinates.map((ring) =>
      ring.map(([lng, lat]) => [
        cx + (lng - cx) * factor,
        cy + (lat - cy) * factor,
      ]),
    ),
  };
}
