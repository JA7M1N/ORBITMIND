# OrbitalMind — Priority Scoring Weights

*Full rationale for each disaster module's component weights. Judges will ask about this.*

---

## Formula

```
Priority Score = w_pop × pop_score
               + w_infra × infra_score
               + w_access × access_score
               + w_intensity × intensity_score
```

Where each component score is normalised to **[0.0, 1.0]** within the current event:

| Component | How it's computed |
|-----------|------------------|
| `pop_score` | `district_population / max_district_population` (in this event) |
| `infra_score` | `(hospitals×3 + schools×2 + bridges×1) / max_weighted_infra` |
| `access_score` | `disrupted_road_km / total_road_km` in the district |
| `intensity_score` | Average SAR / satellite detection confidence of overlapping zones |

---

## Weights by Disaster Type

| Disaster | `w_pop` | `w_infra` | `w_access` | `w_intensity` | Total |
|----------|---------|-----------|------------|---------------|-------|
| 🌊 **Flood** | **0.40** | **0.30** | 0.20 | 0.10 | 1.00 |
| 🔥 **Wildfire** | 0.25 | 0.20 | **0.30** | **0.25** | 1.00 |
| 🏔️ **Landslide** | 0.30 | 0.25 | **0.35** | 0.10 | 1.00 |
| 🌀 **Cyclone** | **0.35** | 0.25 | 0.25 | 0.15 | 1.00 |
| 🌍 **Earthquake** | 0.30 | **0.40** | 0.20 | 0.10 | 1.00 |

---

## Rationale — Flood (w_pop=0.40, w_infra=0.30, w_access=0.20, w_intensity=0.10)

Floods are primarily a **population exposure** problem — flat, densely-settled river plains inundate completely, trapping large numbers of people. Population density is the single strongest predictor of casualty count in flood events (NDMA 2019 Kerala Post-Flood Assessment).

Infrastructure receives the second-highest weight because **hospitals become inaccessible when surrounded by water** — a flooded hospital doesn't just lose patients, it removes the treatment capacity for the entire district. Kerala 2018 saw 19 hospitals evacuated (KSEB report).

Road access is weighted at 0.20 because floods do cut roads, but rescue operations can use **boats** — roads are not the only access mode during active flooding, unlike landslides.

SAR confidence (0.10) is intentionally the smallest weight — by the time a zone is included in results, it already passed a 0.50 confidence threshold. Further variation in confidence within the result set doesn't strongly predict response priority.

---

## Rationale — Wildfire (w_pop=0.25, w_infra=0.20, w_access=0.30, w_intensity=0.25)

Wildfires start in **forested uplands with low population** — Uttarakhand oak-pine belts, not dense towns. Population exposure is therefore the lowest weight of any module.

Access gets the highest weight (0.30) because **evacuation is the primary response mode** for wildfire. Burning forests that block NH-7 or NH-58 trap mountain communities without exit routes. Fire spread models consistently identify road access as the top vulnerability metric (FSI 2023).

Intensity receives an unusually high weight (0.25) because wildfire severity is genuinely bimodal — a high-severity burn (dNBR > 0.66) requires a completely different response (aerial water bombing, hazmat teams) than a low-severity surface fire that a ground crew can handle. The spectral intensity signal directly drives resource allocation decisions.

Infrastructure weight is low (0.20) because **burning structures in a wildfire are typically rural buildings**, not hospitals or bridges. Structural loss is a recovery problem, not an acute rescue problem.

---

## Rationale — Landslide (w_pop=0.30, w_infra=0.25, w_access=0.35, w_intensity=0.10)

Landslides have **one defining characteristic**: they block roads. The 2023 Himachal Pradesh landslides blocked NH-3, NH-5, and NH-21 simultaneously, leaving 300,000+ people cut off for 72+ hours (SDMA HP report). Access weight is the highest of any module at 0.35.

Population is 0.30 because mountain districts have moderate density — small villages are highly exposed but the absolute numbers are lower than flood plains.

Infrastructure is 0.25 because **bridges on mountain highways are the most critical single-point failures** in landslide events. A destroyed bridge on a single-lane hill road can be more disruptive than 10 km of road blockage.

Intensity is the lowest weight (0.10) because SAR amplitude change is a reliable, near-binary signal for landslides — there's less meaningful variation in the confidence signal to exploit.

---

## Rationale — Cyclone (w_pop=0.35, w_infra=0.25, w_access=0.25, w_intensity=0.15)

Cyclone response is dominated by **coastal population exposure** — high-density fishing communities, port towns, and delta settlements in the direct storm path. Population weight is second-highest at 0.35.

Infrastructure and access are equally weighted (0.25) because **storm surge simultaneously floods hospitals AND blocks coastal roads**. Neither effect dominates — both need equal attention in resource allocation.

Intensity receives 0.15 (higher than flood/landslide) because wind speed tier matters operationally: a Category 1 cyclone (< 120 km/h) requires different pre-positioning than a Category 5 (> 220 km/h). The INSAT-3D wind speed data we extract has enough resolution to drive this distinction.

---

## Rationale — Earthquake (w_pop=0.30, w_infra=0.40, w_access=0.20, w_intensity=0.10)

Earthquakes are uniquely an **infrastructure collapse** problem. Unlike floods, where hospitals are flooded-but-intact, an earthquake can collapse a hospital entirely, removing all medical capacity from a zone at the moment when casualties are highest. Infrastructure receives the **highest weight of any module (0.40)**.

The infra formula deliberately weights hospitals at 3×, schools at 2×, bridges at 1×. In earthquakes, schools can collapse during school hours (mass casualties), making them higher-priority than in other disasters.

Access is the lowest non-zero weight (0.20) because rubble can block roads, but **rescue teams use alternative routes, rubble clearance, and air assets** — road disruption is less absolute than in landslides or floods.

Intensity (0.10) uses InSAR coherence loss as a proxy for structural damage extent. Coherence loss is well-correlated with building collapse density (Sentinel-1 InSAR for Earthquake Damage Mapping, Yun et al. 2015), so the signal is reliable, but the weight is kept low because the spatial resolution of 20m InSAR coherence maps doesn't distinguish between a collapsed hospital and a collapsed warehouse.

---

## Infrastructure Weighting Scheme

Within `infra_score`, the relative weights of infrastructure types are:

| Type | Weight | Rationale |
|------|--------|-----------|
| Hospital | **3** | Removing medical capacity is catastrophic — irreplaceable during an emergency |
| School / College | **2** | Mass-occupancy buildings; collapses cause multi-victim incidents |
| Bridge | **1** | Critical but replaceable with temporary crossings or boats |

These sub-weights are **fixed across all disaster types** — only the outer `w_infra` coefficient changes. This ensures consistent infrastructure valuation regardless of disaster context.

---

## Judge FAQ on Weights

**Q: "Why not use equal weights 0.25 each?"**
Equal weights assume all factors matter equally for all disasters. A landslide where 99% of impact is road blockage would have its dominant effect diluted to 25% of the score — leading to wrong prioritisation. Disaster-specific weights encode domain knowledge from NDMA guidelines, academic literature, and post-event assessments.

**Q: "How did you validate these weights?"**
Weights were calibrated against the NDMA 2019 Kerala Post-Flood Report, FSI 2023 Wildfire Loss Assessment, and SDMA HP 2023 Landslide Response Review. For the demo, we verified that the Kerala 2018 flood scoring ranks Ernakulam and Alappuzha (highest population + most hospital density) in the top 3 — consistent with the ground truth that these districts received priority attention in the actual response.

**Q: "Can an admin change these weights?"**
Yes — `scoring_weights` is stored as JSONB in `priority_results`, so every scoring run captures an immutable snapshot of the weights used. The module registry defines the defaults, but the `calculate_priority_score()` function can be extended to accept custom weights as an optional JSONB parameter. This is on the Phase 2 roadmap.
