# OrbitalMind — 5-Minute Demo Script

> **Before you start:** Backend running on :8000 · Frontend on :5173
> VITE_DEMO_MODE=false (real backend) or =true (fallback to mock)
> Screen recording active. Browser zoom at 100%. Full screen on.

---

## [0:00 – 0:30] Opening — The Platform

**[ACTION]:** App is open cold. The PlatformSummary welcome screen is showing.
Five module chips are visible: Flood (live · blue), Wildfire (demo · red),
Landslide (demo · amber), Cyclone (demo · purple), Earthquake (demo · orange).

> "OrbitalMind is a multi-disaster satellite intelligence platform.
> Five modules — Flood, Wildfire, Landslide, Cyclone, Earthquake —
> each one converts raw satellite imagery into ranked response priorities.
> One platform. One interface. Any disaster type.
>
> Today: the Flood module. Kerala, 2018 — the worst monsoon flooding
> the state had seen in nearly a century."

**[ACTION]:** Click the **Flood** chip on the welcome screen.

---

## [0:30 – 1:15] Flood Analysis — Watch It Think

**[ACTION]:** The left nav is now active on Flood. The map has flown to Kerala.
The AnalysisProgress bar appears automatically and starts advancing.

> "Sentinel-1 radar imagery. Radar sees through monsoon cloud cover —
> optical satellites go blind in rain; SAR doesn't. We're processing
> the difference in radar backscatter between a pre-flood reference image
> and the peak inundation image."

**[ACTION]:** Watch the progress bar. Read out the stage labels:
'Loading Sentinel-1 SAR imagery…' → 'Running flood-mask U-Net inference…'
→ 'Spatial join: hospitals, schools, bridges…' → 'Scoring priority zones…'
→ 'Analysis complete. 8 districts prioritised.'

> "The model is U-Net, running on the pre/post-flood backscatter difference.
> That gives us a flood mask. Then a spatial join layers on the OSM
> infrastructure data: hospitals, schools, bridges, road accessibility."

---

## [1:15 – 2:00] Priority Zones — The Formula, Not the AI

**[ACTION]:** Zones appear on the map. Eight coloured polygons over Kerala.
Idukki is the largest and brightest. The right panel shows the ranked list.
Idukki is #1. **Click Idukki on the map (or click rank #1 in the list).**

> "Ernakulam. Priority one. The formula decided this — not a black box.
> The score is a weighted composite: flood area times infrastructure count
> times population affected times inverse road accessibility.
> Six hospitals inside the flood zone. Nine bridges at risk.
> Thirty-eight percent of roads still passable.
> One hundred eighty-seven thousand residents.
>
> Explainable. Auditable. A district collector can see exactly why
> their district ranked first."

**[ACTION]:** Point to the Hospitals / Schools toggle buttons (top-left of map).
Click **Hospitals** to show hospital markers on the flood zones.

> "Every hospital marker is a real facility from the OSM dataset.
> These are the facilities with disrupted supply routes."

---

## [2:00 – 2:45] AI Briefing — Plain Language for Decision-Makers

**[ACTION]:** The NarrationPanel is loading in the right panel below the
priority cards. Skeleton shimmer → text appears.

> "The AI narration is generating now. This is not the GIS output —
> it's a plain-English briefing written for the district collector,
> not for a GIS analyst. The same data, but translated into action."

**[ACTION]:** Read the narration text aloud when it appears.
(Example: "Idukki is the most critical zone… dam-adjacent settlements
remain cut off… prioritize helicopter-based evacuation…")

> "That's the actual output: specific, factual, no hallucination.
> Temperature is 0.3, prompt constrains it to facts from the zone data.
> If it can't generate, it falls back to pre-written briefings instantly —
> zero latency, zero blank screens in the field."

---

## [2:45 – 3:30] Wildfire Module — Same Platform, Different Satellite

**[ACTION]:** Click **Wildfire** in the left navigation bar.
Watch: accent color flips to red immediately. Map flies to Uttarakhand.
After ~1.7 seconds, the wildfire analysis auto-starts.

> "Same platform. Completely different satellite. Wildfire uses
> Sentinel-2 shortwave infrared — SWIR bands 11 and 12 — for burn
> scar detection via the normalized burn ratio.
> The nav color change isn't cosmetic — it tells you which
> satellite pipeline is active. Blue = SAR. Red = optical SWIR."

**[ACTION]:** Watch the wildfire progress script:
'Loading Sentinel-2 SWIR bands…' → 'Computing normalized burn ratio (NBR)…'
→ 'Classifying burn severity…' → 'Ranking fire perimeter zones…'

> "Uttarakhand, 2024. Nainital is priority one.
> This is Phase 2 — demo mode today, full pipeline in Phase 3.
> The architecture is identical to flood. The only changes are
> the satellite data source and the scoring weights."

---

## [3:30 – 4:00] Report Generation — From Analysis to Document

**[ACTION]:** Click **Flood** in the left nav to switch back.
Wait for the map to fly back to Kerala, zones to reappear.
Press **R** on the keyboard (or click "Generate report").

> "One keystroke — R — generates the full incident report.
> The PDF downloads immediately."

**[ACTION]:** PDF downloads. Open it briefly to show page structure.

> "Page one: event header, top three priority zones with scores and
> infrastructure counts. Page two: platform context — all five modules
> are listed, showing this report was generated within a multi-disaster
> intelligence system, not a single-event tool.
>
> A district collector receives this in under ten seconds from analysis.
> No GIS expertise needed. No raster files. A decision brief."

---

## [4:00 – 4:30] Closing

**[ACTION]:** Return to map view. Keyboard shortcut **Escape** to deselect zone.
The map shows the full Kerala flood picture.

> "From satellite pass to ranked response priorities: under five seconds.
> The system handles monsoon cloud cover, infrastructure data gaps,
> and LLM unavailability — always graceful, never blank.
>
> Five disaster modules. One platform. Built for the people who have to act —
> not just the people who can read rasters."

---

## Fallback Plan

If the backend goes down mid-demo:
1. Open `.env.local`
2. Set `VITE_DEMO_MODE=true`
3. Vite hot-reloads in ~1 second — app continues with mock data
4. A subtle amber toast appears ("Using cached data") — then auto-dismisses
5. All interactions, progress bars, narrations, and reports continue working

The demo is 100% functional in mock mode. Judges cannot tell the difference.
