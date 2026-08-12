# OrbitalMind — Frontend Demo Checklist

Complete every item before the demo. Items marked with * are showstoppers.

---

## Environment

- [ ] * `npm run dev` running on port 5173
- [ ] * `VITE_API_URL=http://localhost:8000` in `.env.local`
- [ ] * `VITE_DEMO_MODE=false` (real backend) OR `VITE_DEMO_MODE=true` (mock fallback)
- [ ] Browser zoom at **100%** (Ctrl+0 to reset)
- [ ] Chrome or Firefox (not Safari — MapLibre GL has Safari quirks)
- [ ] Full-screen mode ready (F11)
- [ ] Screen recording software ready (OBS or Windows Game Bar Win+G)

---

## Startup State (Cold Open)

- [ ] * App opens to PlatformSummary welcome screen — not a blank page or error
- [ ] * All 5 module chips visible: Flood (live·blue), Wildfire, Landslide, Cyclone, Earthquake
- [ ] Module chips are clickable and react on hover (no console errors)
- [ ] Map is centered on India at default zoom (not blank or grey)
- [ ] Document title shows "OrbitalMind" in the browser tab

---

## Disaster Module Navigation

- [ ] * Switching modules changes the **accent color** across the entire UI (nav, panel, border)
- [ ] * Map **flies** to the disaster region (Kerala for flood, Uttarakhand for wildfire, etc.)
- [ ] Transition reads as a "platform reveal" — accent flips first, map flies second (250ms gap)
- [ ] Left nav active item is highlighted in the correct accent color
- [ ] Switching modules while analysis is running cancels cleanly (no stuck progress bar)
- [ ] Document title updates to "OrbitalMind — Flood" etc. after module switch settles

---

## Flood Module (Primary Demo Path)

- [ ] * Kerala 2018 event loads automatically
- [ ] * Analysis progress bar appears and advances with SAR-specific messages
  - "Loading Sentinel-1 SAR imagery…"
  - "Running flood-mask U-Net inference…"
  - "Scoring priority zones…"
- [ ] * After analysis: >= 5 priority zones appear on the Kerala map as colored polygons
- [ ] * Idukki is rank #1 (highest priority score)
- [ ] Priority list in right panel is sorted by score descending
- [ ] Clicking a zone on the map selects it in the priority list (and vice versa)
- [ ] Ernakulam, Alappuzha, Kottayam are visible in the list

---

## AI Narration

- [ ] * Clicking a zone triggers narration loading (skeleton shimmer → text)
- [ ] * Narration text appears within 15 seconds
- [ ] Narration is factual (references hospitals, roads, population — not generic)
- [ ] "Copy briefing" button works (text appears in clipboard)
- [ ] Switching zones: old narration fades, skeleton appears, new narration loads
- [ ] If backend is down: amber toast appears, fallback narration still loads
- [ ] No zone shows "narration too short" or empty text

---

## Wildfire Module

- [ ] * Clicking Wildfire in nav: UI turns red, map flies to Uttarakhand
- [ ] * Auto-analysis starts after ~1.7s with wildfire-specific messages:
  - "Loading Sentinel-2 SWIR bands…"
  - "Computing normalized burn ratio (NBR)…"
- [ ] Wildfire priority zones appear (Nainital, Almora, Pauri Garhwal)
- [ ] Module shows "DEMO" status badge (not "LIVE")

---

## Report Generation

- [ ] * "Generate report" button is visible when zones are revealed
- [ ] * Clicking the button (or pressing **R**) downloads a PDF
- [ ] PDF opens correctly (not corrupted)
- [ ] PDF Page 1: event name, top zones with scores
- [ ] PDF Page 2: "Platform context" mentions all 5 disaster modules
- [ ] Report ID in the PDF follows OM-EVENTNAME-TIMESTAMP format
- [ ] Button shows spinner while generating, then "Report ready" flash

---

## Before/After Toggle

- [ ] Toggle appears after zones are revealed
- [ ] Clicking "Pre" hides the zone polygons (opacity → 0)
- [ ] Clicking "Post" shows the zone polygons (opacity → 1)
- [ ] Date labels are correct for each disaster type
- [ ] Transition is smooth (not a snap)

---

## Module Comparison

- [ ] "Compare modules" button opens a comparison panel
- [ ] All 5 modules are shown side by side with their status and stats
- [ ] Closing the comparison panel returns to normal view

---

## Keyboard Shortcuts

- [ ] **Escape** — deselects active zone, map zooms back, panel shows event state
- [ ] **R** — triggers report download when an event with zones is loaded
- [ ] **Arrow Up/Down** — navigates priority list when a zone is selected
- [ ] **D** — toggles nav on mobile

---

## Mobile (Judges May Check on Phone)

- [ ] Below 768px: right panel appears as a bottom sheet (not a sidebar)
- [ ] Bottom sheet slides up when a zone is clicked
- [ ] Bottom sheet drag handle is visible
- [ ] Map is still full height on mobile
- [ ] Swipe down or press Escape to close bottom sheet

---

## Error States / Resilience

- [ ] * With backend running: all API calls succeed, no amber toast
- [ ] With backend down: amber toast appears ("Using cached data"), app still works
- [ ] Toast auto-dismisses after 4 seconds
- [ ] No blank screens, uncaught errors, or white page flashes at any point
- [ ] Console has no unhandled promise rejections or React errors

---

## Design Quality Check

Run this check from a judge's perspective:

1. **Cold open** — does PlatformSummary wow in 5 seconds? (Premium headline, 5 module chips, clear CTA)
2. **Module switch** — does it feel like a platform reveal or just a color change?
   It should feel like switching between mission control modes.
3. **PDF** — would a district collector actually use this document?
   (Event date, zone scores, infrastructure counts, clear action items)
4. **Every interaction** — is anything jarring, slow (>400ms delay felt), or generic?
5. **Compare vs Linear.app / Vercel** — does OrbitalMind belong in that tier?
   Dark background, Inter font, mono numbers, glass panels, accent transitions.

---

## Fallback Plan (Keep This Tab Open)

If the backend fails during the demo:
```
1. Open frontend/.env.local
2. Change VITE_DEMO_MODE=true
3. Save — Vite hot-reloads in ~1s
4. App continues with mock data, all interactions work
5. Amber toast auto-dismisses — judges may not even notice
```

Mock data is grounded in real 2011 census figures and real district names.
The demo is indistinguishable from the live backend in DEMO_MODE.
