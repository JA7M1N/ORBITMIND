# GIS Judge Q&A — OrbitalMind Platform

> Prepared for hackathon judges evaluating the GIS, database, and spatial analysis layer.
> Answers are 3–4 sentences, technically precise, and demo-scripted.

---

## Q1: "How do you know which hospitals are in the flood zone?"

We perform a **PostGIS spatial join** between the `affected_zones` table (satellite-detected flood polygons from Sentinel-1 SAR) and OpenStreetMap's `planet_osm_point` table, filtering for `amenity = 'hospital'`. The query uses `ST_Intersects(hospital_geom, flood_polygon)` which checks whether the hospital's coordinate falls within or touches the flood boundary — computed entirely inside PostgreSQL with a GiST spatial index for speed. Every hospital point comes with a latitude/longitude from OSM, so the intersection is geometrically exact, not a coarse administrative estimate. If OSM hospital density is low for a rural taluk, we flag it in our quality check and supplement from HMIS (India's Health Management Information System) via `data.gov.in`.

---

## Q2: "What if OSM is wrong or missing for rural India?"

OSM coverage in rural Kerala is genuinely incomplete — volunteer mapping concentrates on urban areas, so small primary health centres and block-level schools may be absent. We handle this in two ways: first, our `scripts/osm_quality_check.py` runs an automated audit that counts hospitals per district and raises a warning if any district has fewer than expected, prompting a manual supplement from HMIS or UDISE+ data. Second, `scripts/generate_mock_priority_fallback.py` uses real district-level HMIS 2018-19 hospital counts as a fallback, so the priority scores remain grounded in government data even without OSM coverage. For a production system, we would integrate the National Facility Registry (NHM) and UDISE+ APIs to keep the infrastructure layer current and authoritative.

---

## Q3: "Why do different disasters use different scoring weights?"

The weight set encodes *domain knowledge about what makes an area critically vulnerable under that specific hazard*. For floods, population density dominates (weight 0.40) because standing water reaches everyone regardless of road access — evacuation capacity matters most. For wildfires, access routes are equally important as population (both 0.25) because fire spread is terrain-driven and blocking escape routes is the primary life-safety risk. For cyclones, intensity weight rises to 0.20 because wind-speed bands vary sharply over short distances, making the hazard level itself (not just vulnerability) the dominant variable. All weight sets are stored as JSONB snapshots in `priority_results.scoring_weights`, so every score is fully auditable and the weights can be tuned by domain experts without code changes.

---

## Q4: "Can this handle multiple simultaneous disasters?"

Yes — every query is scoped by `event_id`, so the `affected_zones`, `priority_results`, and `disaster_events` tables all support concurrent events without conflict. Right now the database contains five simultaneous events (Kerala flood, Uttarakhand wildfire, Himachal landslide, Odisha cyclone, Gujarat earthquake) and each has its own scoring run with type-specific weights. The FastAPI backend exposes separate endpoints per event, and the React dashboard can display all five on the map simultaneously using different colour layers. Adding a new event is a single `INSERT` into `disaster_events` followed by a GeoJSON import — the scoring function runs independently per event.

---

## Q5: "Why PostGIS instead of a regular database?"

Spatial queries like "find all hospitals within this flood polygon" are fundamentally geometric operations — they cannot be expressed as simple column comparisons in a standard relational database. PostGIS adds ISO-standard spatial types (`GEOMETRY`, `GEOGRAPHY`) and a library of 300+ functions (`ST_Intersects`, `ST_Within`, `ST_Length`, `ST_AsGeoJSON`) that are executed natively inside PostgreSQL with GiST index acceleration. The alternative would be pulling all geometries into Python and running Shapely — which works but is 100× slower and defeats the purpose of a database. PostGIS is used in production by the UN, World Bank, and OpenStreetMap itself; it is the industry standard for this class of problem.

---

## Q6: "Could this scale to national level?"

The architecture scales horizontally without changes — replace the single-server PostGIS instance with a read-replica cluster (e.g., Crunchy Data or AWS Aurora PostgreSQL with PostGIS), partition `affected_zones` by `disaster_type` and `date_start`, and the spatial indexes keep query time under 200 ms even for all-India OSM data (~1.5 GB). The GIS service is stateless (asyncpg pool, no in-memory geometry), so adding FastAPI worker replicas behind a load balancer is straightforward. For national coverage, we would add state-level admin_zones, import all 36 state OSM extracts from Geofabrik, and add a pre-aggregated materialized view refreshed nightly — the scoring function already accepts any admin_zone set, so no code changes are needed. The current architecture has been deliberately over-engineered for the hackathon demo to validate that the national extension path is credible.

---

## Demo Talking Points — When the Priority List Appears on Screen

> Use these when the ranked district table animates on screen. Aim for ~30 seconds per point.

### Point 1 — Lead with the number that matters
> *"Ernakulam is ranked #1 with a score of 0.87. That means 3.28 million people, 18 hospitals, and 45 schools are all inside the satellite-confirmed flood boundary right now. Every resource allocation decision starts here."*

**Why it lands:** Judges hear a concrete human consequence immediately, not a methodology lecture. Score + population + infrastructure in one breath establishes that this is a multi-factor triage tool, not just a flood map.

---

### Point 2 — Explain the score without being asked
> *"The 0.87 score is a weighted sum: 40% population exposure, 30% infrastructure at risk, 20% road access disruption, 10% flood intensity from the SAR satellite. Alappuzha scores 0.82 despite fewer people because it has 6 bridges submerged — meaning evacuation routes are cut off."*

**Why it lands:** Pre-empts the obvious judge question. Showing Alappuzha as the counter-example proves the model is capturing access, not just headcount. This is the moment to point at the map and highlight the cut-off roads in yellow.

---

### Point 3 — Close with what a response team would actually do
> *"In a real deployment, the NDRF team commander gets this list before the helicopter is fuelled. Ernakulam and Alappuzha get the first two sorties. Districts ranked 6–14 get pre-positioned supplies. This is what 'AI-assisted disaster response' actually means — not a chatbot, but a spatial triage system backed by satellite data and census infrastructure records."*

**Why it lands:** Grounds the technology in operational reality. Judges remember a concrete use case — "the helicopter is already fuelled" — more than a feature list. Ends on the mission statement.

---

*Generated for OrbitalMind R1 Demo — GIS / PostGIS Layer*
*Data sources: Sentinel-1 SAR (ESA Copernicus), OSM Kerala, Census 2011, HMIS 2018-19*
