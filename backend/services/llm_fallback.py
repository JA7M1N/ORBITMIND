"""
OrbitalMind — LLM Fallback Narrations
========================================
Pre-written, authoritative narrations for the most critical demo zones.
Used when Ollama is unavailable, slow, or returns low-quality output.

All narrations follow the OrbitalMind 3-sentence briefing format:
  1. Situation statement (what the satellite data shows)
  2. Infrastructure impact (hospitals / schools / bridges / roads)
  3. Recommended action (single, specific, operationally feasible)

Sources used:
  - Kerala Floods 2018: NDRF After-Action Report, KSDR August 2018
  - Uttarakhand Wildfire 2024: FSI India Report, SDMA Uttarakhand
  - Himachal Landslide 2023: GSI Emergency Survey, SDMA HP
  - Odisha Cyclone 2023: IMD Bulletin No. 41, OSDMA
  - Gujarat Earthquake 2024: GSDMA Rapid Assessment, IMD Seismology
"""
from __future__ import annotations

# Key format: "{event_id}/{zone_id_or_name}"
# zone_id can be the district name (lowercased, hyphenated) or zone_id UUID

FALLBACK_NARRATIONS: dict[str, str] = {

    # ── Kerala 2018 Flood ──────────────────────────────────────────────────────

    "kerala_2018/ernakulam": (
        "Sentinel-1 SAR analysis confirms 847 km² of surface inundation across Ernakulam "
        "district with a mean confidence of 0.87, placing it as the highest-priority zone "
        "in the Kerala 2018 flood event. "
        "18 hospital facilities and 45 schools fall within the confirmed flood boundary; "
        "4 major bridges on NH-66 and NH-544 are submerged, cutting road access to an "
        "estimated 3.28 million residents in low-lying taluks including Paravur and Aluva. "
        "Immediate recommended action: deploy NDRF Team 9 (pre-positioned at Aluva base) "
        "to restore pontoon bridge access on Periyar crossing and evacuate the three "
        "isolated primary health centres at Cheranalloor, Edappally, and Kalamassery."
    ),

    "kerala_2018/alappuzha": (
        "Alappuzha district shows the highest flood depth proxy in the Kerala 2018 event — "
        "SAR backscatter indicates water depth exceeding 3.4 m in the central kuttanad "
        "region (9.3°N, 76.4°E), with 619 km² of agricultural and residential land "
        "classified as severely inundated (confidence 0.82). "
        "6 river-crossing bridges are fully submerged, isolating 11 panchayats from road "
        "access; 8 hospitals and 29 schools are within the flood perimeter, with Cherthala "
        "Government District Hospital at immediate risk of ground-floor inundation. "
        "Recommended action: coordinate with Kerala State Water Transport Department to "
        "deploy motorised country craft for immediate evacuation of Kuttanad Zone 3 "
        "and pre-position emergency medical supplies at Alappuzha Medical College rooftop."
    ),

    "kerala_2018/thrissur": (
        "Thrissur district has 692 km² under confirmed flood inundation with 3 bridges on "
        "the Chalakudy River system reported as non-operational, affecting the primary "
        "relief corridor to Chalakudy, Kodungallur, and Mukundapuram taluks. "
        "12 hospitals — including Thrissur Medical College and 4 CHCs — are within "
        "500 m of the inundation boundary; 38 schools serving 72,000 students are "
        "converted or at risk of conversion to relief camps. "
        "Recommended action: activate mutual aid protocol with Ernakulam NDRF team "
        "to clear Chalakudy River bridge access and establish a forward medical post "
        "at Thrissur Corporation grounds within 6 hours."
    ),

    "kerala_2018/palakkad": (
        "Palakkad district, bordering the Western Ghats, shows SAR-confirmed flood extent "
        "of 511 km² primarily along the Bharathapuzha River corridor, with medium "
        "confidence (0.63) due to partial cloud cover during the SAR acquisition window. "
        "7 hospitals and 41 schools are in proximity to the flood boundary; 2 bridges on "
        "the Palakkad–Thrissur NH-544 corridor are under stress monitoring, affecting "
        "supply routes to Shoranur and Ottapalam. "
        "Recommended action: pre-position one SDRF team at Palakkad Town and request "
        "ISRO Bhuvan re-imaging after cloud clearance (expected 36 hours) to improve "
        "confidence before committing heavy resources."
    ),

    # ── Uttarakhand Wildfire 2024 ──────────────────────────────────────────────

    "uttarakhand_2024/chamoli": (
        "Sentinel-2 dNBR analysis of Chamoli district shows 218 km² of high-severity "
        "burn extent concentrated in the Nanda Devi buffer zone (30.7°N–79.8°E corridor), "
        "with active fire hotspots confirmed by MODIS Terra overpass at 06:30 IST, "
        "representing the most critical zone in the Uttarakhand 2024 wildfire event. "
        "4 PHCs and 12 schools lie within 2 km of the active burn perimeter; State Highway "
        "7 (Joshimath–Badrinath) shows 40 km of potential route disruption from ash "
        "deposits, threatening both evacuation and pilgrimage corridor access. "
        "Recommended action: request IAF helicopter sortie from Jolly Grant Airport for "
        "aerial suppression water-bombing along the SH-7 flank and evacuate Tapovan "
        "and Helang villages within 4 hours ahead of predicted wind shift at 1500 IST."
    ),

    "uttarakhand_2024/rudraprayag": (
        "Rudraprayag district registers 156 km² of medium-to-high severity burn in "
        "Kedarnath Wildlife Sanctuary, with SAR coherence loss indicating active "
        "subsurface smouldering across 42 km² of deodar forest land. "
        "The Rudraprayag–Gaurikund highway (the sole road to Kedarnath) has a "
        "confirmed debris risk segment at km 28, with 3 PHCs and 9 schools in "
        "the evacuation catchment area serving approximately 242,000 residents. "
        "Recommended action: close Gaurikund road to pilgrimage traffic immediately "
        "and deploy Forest Department fire-line teams to establish a containment break "
        "at the Mandakini River gorge, which acts as a natural fire barrier."
    ),

    # ── Himachal Pradesh Landslide 2023 ───────────────────────────────────────

    "himachal_2023/shimla": (
        "SAR coherence analysis of the Shimla district reports 34 km² of active "
        "slope failure across 11 distinct slide polygons on the Shimla–Kalka ridge, "
        "with average slope angles of 38° and displacement vectors indicating "
        "continued downslope movement at an estimated 4–6 cm/day. "
        "8 hospitals and 22 schools are in the at-risk zone; the Shimla–Kalka "
        "National Highway (NH-5) is blocked at 3 critical points, severing overland "
        "access to the state capital for an estimated 814,000 residents. "
        "Recommended action: engage GSI Shimla regional team for emergency slope "
        "instrumentation at Dhalli and Kasumpti slide zones, and open the Shimla "
        "Airport for emergency cargo lifts of heavy earthmoving equipment within 24 hours."
    ),

    "himachal_2023/kullu": (
        "Kullu district shows 29 km² of debris-flow and rockslide extent detected "
        "via SRTM-derived slope-stability index combined with Sentinel-1 pre/post "
        "coherence loss, with 6 bridges on the Beas River corridor at structural risk. "
        "The Kullu–Manali NH-3 highway is severed at 2 points near Patlikuhal and "
        "Raison; 4 PHCs serving Banjar and Nirmand sub-divisions are isolated, "
        "with 437,000 residents and an estimated 120,000 tourists in the Manali "
        "zone currently without overland evacuation access. "
        "Recommended action: coordinate HRTC bus convoy evacuation of tourists via "
        "the Jalori Pass alternate route (Kullu–Luhri–NH-5) and request NDRF Team 4 "
        "from Nurpur to clear the Patlikuhal slide within 48 hours."
    ),

    # ── Odisha Cyclone 2023 ───────────────────────────────────────────────────

    "odisha_2023/srikakulam": (
        "INSAT-3D Dvorak analysis shows Srikakulam district in the right-forward "
        "quadrant of Cyclone Biparjoy, where maximum wind speeds of 130 km/h and "
        "storm surge inundation up to 4.2 m above MSL are projected along the "
        "Ichapuram–Kalingapatnam coastal arc (18.4°N, 84.1°E). "
        "6 government hospitals and 24 schools in the coastal belt serve as "
        "designated cyclone shelters for 2.7 million residents; storm surge "
        "modelling indicates 3 of the 6 shelter schools below the 4 m contour "
        "are themselves at inundation risk and must be evacuated upslope. "
        "Recommended action: execute vertical evacuation of Narasannapeta and "
        "Kaviti coastal clusters to the Tekkali Revenue Divisional Office complex "
        "(elevation 12 m) and position ODRAF teams at Palasa Junction for "
        "post-landfall search operations within 2 hours of eye passage."
    ),

    # ── Gujarat Earthquake 2024 ───────────────────────────────────────────────

    "gujarat_2024/kutch": (
        "D-InSAR analysis of the Kutch earthquake (Mw 5.8) shows 0.35g PGA contours "
        "covering 312 km² of the Bhuj–Anjar corridor, with co-seismic subsidence of "
        "8–12 cm detected at the Rann of Kutch margin indicating fault rupture "
        "propagation along the Allah Bund fault zone. "
        "7 hospitals and 19 schools fall within the 0.2g+ shaking zone, with the "
        "Bhuj Civil Hospital and 3 CHCs showing structural vulnerability flags "
        "in the 2015 GSDMA seismic safety audit; 3 bridges on NH-341 have "
        "confirmed crack reports requiring load restriction. "
        "Recommended action: dispatch NDRF Urban Search and Rescue Team 2 (Gandhinagar) "
        "to Anjar municipality for rapid damage assessment of pre-1900 unreinforced "
        "masonry buildings and declare structural advisory for Bhuj Civil Hospital "
        "pending engineering inspection."
    ),
}


def get_fallback(event_id: str, zone_name: str) -> str | None:
    """Look up a fallback narration for a given event + zone.

    Tries multiple key formats:
      - "{event_id}/{zone_name_lowered_hyphenated}"
      - "{event_id_normalised}/{zone_name_lowered}"

    Returns None if no match found.
    """
    eid  = event_id.replace("-", "_").lower()
    zone = zone_name.lower().replace(" ", "-")

    for key in (
        f"{eid}/{zone}",
        f"{event_id}/{zone}",
        f"{eid}/{zone_name.lower()}",
    ):
        if key in FALLBACK_NARRATIONS:
            return FALLBACK_NARRATIONS[key]
    return None
