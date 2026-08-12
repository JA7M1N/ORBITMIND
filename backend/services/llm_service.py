"""
OrbitalMind — LLM Narration Service
======================================
Generates disaster-aware 3-sentence briefings for priority zones using
a local Ollama LLM (llama3.2:3b by default).

Fallback chain
--------------
1. DB cache: check priority_results.llm_narrative (< 1 ms)
2. Ollama inference: ~4–10 s on CPU; ~1–3 s if GPU available
3. Fallback cache: hardcoded narrations in llm_fallback.py
4. Generic template: last-resort assembled from field data

VRAM note (RTX 3050)
--------------------
Never call generate_narration() while FloodModule inference is running.
The U-Net uses the full 4 GB VRAM; Ollama needs ~2 GB for llama3.2:3b.
Check task_progress[task_id]["status"] == "complete" before calling this.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional

from backend.config import settings
from backend.services.llm_fallback import get_fallback

log = logging.getLogger(__name__)


# ── Prompt templates (one per disaster type) ──────────────────────────────────

PROMPT_TEMPLATES: dict[str, str] = {

    "flood": """You are an emergency response AI assisting Indian district authorities during a flood disaster.
Write a concise 3-sentence situation briefing for the following zone. Use only the data provided — no assumptions.

Zone: {zone_name} | Priority #{rank} of {total}
Flooded area: {area_km2:.1f} km² | Detection confidence: {confidence:.0%}
Hospitals in flood zone: {hospitals} | Schools: {schools} | Bridges at risk: {bridges}
Road accessibility: {road_pct:.0f}% intact | Affected population: {pop:,}
Satellite source: Sentinel-1 SAR (C-band) | Analysis: Attention U-Net

Rules:
- Use factual language. No emojis. No speculation beyond the data.
- Sentence 1: Describe what the satellite data shows (area, confidence, location).
- Sentence 2: Describe the infrastructure impact (hospitals, schools, bridges, roads).
- Sentence 3: State ONE specific, operationally feasible recommended action.
- Total length: 60–90 words.

Briefing:""",

    "wildfire": """You are an emergency response AI assisting Indian forest and revenue authorities during a wildfire.
Write a concise 3-sentence situation briefing. Use only the data provided.

Zone: {zone_name} | Priority #{rank} of {total}
Burned area: {area_km2:.1f} km² | Detection confidence: {confidence:.0%}
High-severity burn: {high_severity_pct:.0f}% of affected area
Hospitals near perimeter: {hospitals} | Schools: {schools} | Roads disrupted: {roads_disrupted_km:.0f} km
Affected population: {pop:,}
Satellite source: Sentinel-2 SWIR dNBR

Rules:
- No emojis. Facts only. Sentence 3 must contain a single specific action.
- Sentence 1: Satellite data summary (extent, severity, location).
- Sentence 2: Infrastructure and population impact.
- Sentence 3: ONE specific recommended action (evacuation, containment line, resource deployment).
- Total length: 60–90 words.

Briefing:""",

    "landslide": """You are an emergency response AI assisting Indian district disaster management authorities.
Write a concise 3-sentence situation briefing for a landslide-affected zone.

Zone: {zone_name} | Priority #{rank} of {total}
Slide area: {area_km2:.1f} km² | Detection confidence: {confidence:.0%}
Average slope angle: {avg_slope_deg:.0f}° | Estimated displacement: {displacement_cm:.1f} cm/day
Hospitals in risk zone: {hospitals} | Schools: {schools} | Roads blocked: {roads_blocked}
Affected population: {pop:,}
Satellite source: Sentinel-1 InSAR coherence + SRTM DEM

Rules:
- No emojis. Facts only. Sentence 3: one specific action.
- Sentence 1: Describe slope failure extent and movement detected.
- Sentence 2: Infrastructure impact (roads, hospitals, schools).
- Sentence 3: ONE specific recommended action (slope instrumentation, highway closure, evacuation).
- Total length: 60–90 words.

Briefing:""",

    "cyclone": """You are an emergency response AI assisting Indian coastal district authorities during a cyclone.
Write a concise 3-sentence situation briefing. Use only the data provided.

Zone: {zone_name} | Priority #{rank} of {total}
Max wind speed: {wind_speed_kmh:.0f} km/h | Storm surge: {storm_surge_m:.1f} m above MSL
Coastal area at risk: {area_km2:.1f} km² | Detection confidence: {confidence:.0%}
Hospitals in impact zone: {hospitals} | Schools (shelters): {schools} | Bridges: {bridges}
Coastal population at risk: {pop:,}
Satellite source: INSAT-3D IR + WV (Dvorak technique)

Rules:
- No emojis. Facts only. Sentence 3: one specific action.
- Sentence 1: Storm intensity and surge projection from INSAT-3D data.
- Sentence 2: Infrastructure and shelter capacity impact.
- Sentence 3: ONE specific pre-landfall action (evacuation, shelter-in-place, road closure).
- Total length: 60–90 words.

Briefing:""",

    "earthquake": """You are an emergency response AI assisting Indian earthquake response authorities.
Write a concise 3-sentence situation briefing. Use only the data provided.

Zone: {zone_name} | Priority #{rank} of {total}
Damage area: {area_km2:.1f} km² | Peak Ground Acceleration: {pga_g:.2f}g
Estimated structural damage: {destroyed_pct:.0f}% of buildings in zone
Hospitals in damage zone: {hospitals} | Schools: {schools} | Bridges: {bridges}
Affected population: {pop:,}
Satellite source: Sentinel-1 D-InSAR + USGS ShakeMap

Rules:
- No emojis. Facts only. Sentence 3: one specific action.
- Sentence 1: Seismic impact summary (PGA, damage extent, location).
- Sentence 2: Infrastructure damage and hospital/shelter status.
- Sentence 3: ONE specific recommended action (USAR deployment, hospital triage, route clearance).
- Total length: 60–90 words.

Briefing:""",
}


# ── Generic fallback template (last resort) ───────────────────────────────────

_GENERIC_TEMPLATE = (
    "{zone_name} is ranked Priority #{rank} with a composite score of {score:.2f}. "
    "Satellite analysis confirms {area_km2:.1f} km² of affected area with "
    "{confidence:.0%} detection confidence; {hospitals} hospitals, {schools} schools, "
    "and {bridges} bridges are within the impact zone, affecting approximately "
    "{pop:,} residents. "
    "Emergency management authorities should prioritise this district for initial "
    "resource deployment based on its combined population exposure and infrastructure vulnerability."
)


# ── LLM Service ───────────────────────────────────────────────────────────────

class LLMService:
    """Async service for generating disaster zone narrations via Ollama.

    Usage
    -----
    ::

        svc = LLMService()
        text = await svc.generate_narration(zone_data, "flood")
    """

    def __init__(self) -> None:
        self._url   = settings.OLLAMA_URL
        self._model = settings.OLLAMA_MODEL

    # ── Public API ─────────────────────────────────────────────────────────

    async def generate_narration(
        self,
        zone_data:    dict[str, Any],
        disaster_type: str,
    ) -> tuple[str, str]:
        """Generate a 3-sentence zone briefing.

        Tries Ollama first; falls back to pre-written narration or generic
        template if the model is unavailable or times out.

        Parameters
        ----------
        zone_data : dict
            Zone metrics dict. Must include at minimum: zone_name, rank,
            priority_score, area_km2, confidence, hospitals, schools, bridges, pop.
        disaster_type : str
            Module routing key — selects the appropriate prompt template.

        Returns
        -------
        tuple[str, str]
            (narration_text, source) where source is one of:
            "ollama", "fallback_cache", "generic_template"
        """
        zone_name = zone_data.get("zone_name") or zone_data.get("zone", "Unknown Zone")
        event_id  = zone_data.get("event_id", "")

        # 1. Try Ollama
        try:
            text = await asyncio.wait_for(
                self._call_ollama(zone_data, disaster_type),
                timeout=12.0,
            )
            if text and len(text.strip()) > 40:
                return text.strip(), "ollama"
        except asyncio.TimeoutError:
            log.warning("Ollama timeout for %s/%s — using fallback", event_id, zone_name)
        except Exception as exc:
            log.warning("Ollama error for %s/%s: %s — using fallback", event_id, zone_name, exc)

        # 2. Pre-written fallback cache
        cached = get_fallback(event_id, zone_name)
        if cached:
            return cached, "fallback_cache"

        # 3. Generic assembled template (last resort)
        text = _GENERIC_TEMPLATE.format(
            zone_name   = zone_name,
            rank        = zone_data.get("rank", zone_data.get("priority_rank", "?")),
            score       = float(zone_data.get("score", zone_data.get("priority_score", 0))),
            area_km2    = float(zone_data.get("area_km2", 0)),
            confidence  = float(zone_data.get("confidence", 0.5)),
            hospitals   = zone_data.get("hospitals", zone_data.get("hospitals_affected", 0)),
            schools     = zone_data.get("schools", zone_data.get("schools_affected", 0)),
            bridges     = zone_data.get("bridges", zone_data.get("bridges_affected", 0)),
            pop         = int(zone_data.get("pop", zone_data.get("population", 0))),
        )
        return text, "generic_template"

    async def check_availability(self) -> dict[str, Any]:
        """Ping Ollama and check if the configured model is available.

        Returns
        -------
        dict
            {available: bool, model: str, models: list, error: str|None}
        """
        try:
            import httpx
            async with httpx.AsyncClient(timeout=3.0) as client:
                r = await client.get(f"{self._url}/api/tags")
                if r.status_code != 200:
                    return {"available": False, "model": self._model,
                            "models": [], "error": f"HTTP {r.status_code}"}
                data   = r.json()
                models = [m["name"] for m in data.get("models", [])]
                avail  = any(
                    self._model in m or m.startswith(self._model.split(":")[0])
                    for m in models
                )
                return {
                    "available": avail,
                    "model":     self._model,
                    "models":    models,
                    "error":     None if avail else f"Model '{self._model}' not pulled. Run: ollama pull {self._model}",
                }
        except Exception as exc:
            return {
                "available": False,
                "model":     self._model,
                "models":    [],
                "error":     f"Ollama not reachable at {self._url}: {exc}",
            }

    # ── Internal helpers ───────────────────────────────────────────────────

    async def _call_ollama(self, zone_data: dict, disaster_type: str) -> str:
        """Build the disaster-specific prompt and call Ollama chat API."""
        template = PROMPT_TEMPLATES.get(disaster_type, PROMPT_TEMPLATES["flood"])

        # Build prompt kwargs — fill missing fields with safe defaults
        kwargs = _build_prompt_kwargs(zone_data, disaster_type)
        prompt = template.format(**kwargs)

        # Use httpx async client (works without the ollama pip package)
        import httpx
        async with httpx.AsyncClient(timeout=11.0) as client:
            r = await client.post(
                f"{self._url}/api/chat",
                json={
                    "model":  self._model,
                    "stream": False,
                    "options": {
                        "temperature":   0.3,   # low temp = factual, consistent
                        "num_predict":   150,   # ~90 words — tight briefing
                        "repeat_penalty": 1.1,
                        "top_p":         0.9,
                    },
                    "messages": [
                        {"role": "user", "content": prompt},
                    ],
                },
            )
        r.raise_for_status()
        data = r.json()
        return data["message"]["content"]


# ── Prompt kwargs builder ─────────────────────────────────────────────────────

def _build_prompt_kwargs(zone_data: dict, disaster_type: str) -> dict[str, Any]:
    """Extract and normalise zone_data fields into template kwargs.

    Provides safe defaults for every template field so format() never raises.
    """
    pop         = int(zone_data.get("pop") or zone_data.get("population") or 0)
    hospitals   = int(zone_data.get("hospitals") or zone_data.get("hospitals_affected") or 0)
    schools     = int(zone_data.get("schools") or zone_data.get("schools_affected") or 0)
    bridges     = int(zone_data.get("bridges") or zone_data.get("bridges_affected") or 0)
    rank        = zone_data.get("rank") or zone_data.get("priority_rank") or 1
    score       = float(zone_data.get("score") or zone_data.get("priority_score") or 0)
    confidence  = float(zone_data.get("confidence") or 0.75)
    area_km2    = float(zone_data.get("area_km2") or 0)
    zone_name   = zone_data.get("zone_name") or zone_data.get("zone") or "Unknown Zone"
    total       = int(zone_data.get("total_zones") or 8)

    base = dict(
        zone_name   = zone_name,
        rank        = rank,
        total       = total,
        score       = score,
        area_km2    = area_km2,
        confidence  = confidence,
        hospitals   = hospitals,
        schools     = schools,
        bridges     = bridges,
        pop         = pop,
        road_pct    = float(zone_data.get("road_pct") or zone_data.get("roads_intact_pct") or 65),
    )

    if disaster_type == "wildfire":
        base.update({
            "high_severity_pct":  float(zone_data.get("high_severity_pct") or 35),
            "roads_disrupted_km": float(zone_data.get("roads_disrupted_km") or 40),
        })
    elif disaster_type == "landslide":
        base.update({
            "avg_slope_deg":   float(zone_data.get("avg_slope_deg") or 38),
            "displacement_cm": float(zone_data.get("displacement_cm") or 5),
            "roads_blocked":   int(zone_data.get("roads_blocked") or bridges),
        })
    elif disaster_type == "cyclone":
        base.update({
            "wind_speed_kmh":  float(zone_data.get("wind_speed_kmh") or 110),
            "storm_surge_m":   float(zone_data.get("storm_surge_m") or 2.5),
        })
    elif disaster_type == "earthquake":
        base.update({
            "pga_g":          float(zone_data.get("pga_g") or 0.3),
            "destroyed_pct":  float(zone_data.get("destroyed_pct") or 15),
        })

    return base
