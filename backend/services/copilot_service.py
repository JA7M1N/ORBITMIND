"""
OrbitalMind — EO Copilot Service
==================================
Handles context building, LLM querying, and MAP_ACTION parsing
for the conversational copilot feature.

This service is intentionally narrow: it only answers questions
about data it has been given in the context block. It never
speculates or invents information.

Architecture note
-----------------
DEMO_MODE=True  → context built from hardcoded fixture strings
                  (fast, no DB, exactly what disaster managers see)
DEMO_MODE=False → context built from a live PostGIS query on
                  priority_results joined with admin_zones

MAP_ACTION tags are stripped from the LLM output before returning
to the client. The client receives a clean ``reply`` plus an
optional structured ``map_action`` dict.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

import ollama

from backend.config import settings

logger = logging.getLogger(__name__)

# ── MAP_ACTION regex ──────────────────────────────────────────────────────────
# Matches: MAP_ACTION::ACTION_TYPE::TARGET (remainder of the line)
_MAP_ACTION_RE = re.compile(
    r"MAP_ACTION::(?P<action>[A-Z]+)::(?P<target>[^\n]+)",
    re.MULTILINE,
)

# ── Demo context fixtures ────────────────────────────────────────────────────
# These mirror the mock data used by the frontend exactly so that the
# copilot gives coherent answers during demo sessions without a live DB.

_DEMO_CONTEXTS: dict[str, str] = {
    "kerala-2018": """\
DISASTER EVENT: Kerala Floods 2018 | TYPE: flood | DATE: 2018-08-08
SATELLITE SOURCE: Sentinel-1 SAR (C-band, VV polarisation)

ZONE PRIORITY RANKINGS (calculated from satellite + infrastructure data):

Rank 1: Idukki
  Priority Score: 0.94/1.0
  Population Affected: 187,500
  Hospitals in Impact Zone: 6
  Schools in Impact Zone: 42
  Bridges at Risk: 9
  Road Accessibility: 38% of roads passable
  Detection Confidence: 91%

Rank 2: Alappuzha
  Priority Score: 0.89/1.0
  Population Affected: 412,300
  Hospitals in Impact Zone: 11
  Schools in Impact Zone: 68
  Bridges at Risk: 5
  Road Accessibility: 45% of roads passable
  Detection Confidence: 88%

Rank 3: Kottayam
  Priority Score: 0.82/1.0
  Population Affected: 298,100
  Hospitals in Impact Zone: 8
  Schools in Impact Zone: 51
  Bridges at Risk: 4
  Road Accessibility: 52% of roads passable
  Detection Confidence: 86%

Rank 4: Pathanamthitta
  Priority Score: 0.78/1.0
  Population Affected: 176,900
  Hospitals in Impact Zone: 5
  Schools in Impact Zone: 33
  Bridges at Risk: 7
  Road Accessibility: 41% of roads passable
  Detection Confidence: 83%

Rank 5: Ernakulam
  Priority Score: 0.71/1.0
  Population Affected: 521,400
  Hospitals in Impact Zone: 14
  Schools in Impact Zone: 77
  Bridges at Risk: 3
  Road Accessibility: 61% of roads passable
  Detection Confidence: 89%

Rank 6: Thrissur
  Priority Score: 0.64/1.0
  Population Affected: 289,600
  Hospitals in Impact Zone: 9
  Schools in Impact Zone: 46
  Bridges at Risk: 2
  Road Accessibility: 67% of roads passable
  Detection Confidence: 84%

Rank 7: Wayanad
  Priority Score: 0.58/1.0
  Population Affected: 94,200
  Hospitals in Impact Zone: 3
  Schools in Impact Zone: 21
  Bridges at Risk: 6
  Road Accessibility: 55% of roads passable
  Detection Confidence: 79%

Rank 8: Malappuram
  Priority Score: 0.47/1.0
  Population Affected: 218,700
  Hospitals in Impact Zone: 7
  Schools in Impact Zone: 39
  Bridges at Risk: 1
  Road Accessibility: 74% of roads passable
  Detection Confidence: 81%
""",

    "uttarakhand-wildfire-2024": """\
DISASTER EVENT: Uttarakhand Forest Fires 2024 | TYPE: wildfire | DATE: 2024-05-02
SATELLITE SOURCE: Sentinel-2 SWIR (Bands 11+12, Normalised Burn Ratio)

ZONE PRIORITY RANKINGS (calculated from satellite + infrastructure data):

Rank 1: Nainital
  Priority Score: 0.88/1.0
  Population Affected: 42,300
  Hospitals Near Perimeter: 2
  Schools in Evacuation Zone: 14
  Roads Blocked by Fire: 3
  Road Accessibility: 58% of roads passable
  Detection Confidence: 76%

Rank 2: Almora
  Priority Score: 0.74/1.0
  Population Affected: 28,100
  Hospitals Near Perimeter: 1
  Schools in Evacuation Zone: 9
  Roads Blocked by Fire: 2
  Road Accessibility: 63% of roads passable
  Detection Confidence: 72%

Rank 3: Pauri Garhwal
  Priority Score: 0.61/1.0
  Population Affected: 19,700
  Hospitals Near Perimeter: 1
  Schools in Evacuation Zone: 7
  Roads Blocked by Fire: 1
  Road Accessibility: 70% of roads passable
  Detection Confidence: 69%
""",

    "himachal-landslide-2023": """\
DISASTER EVENT: Himachal Pradesh Landslides 2023 | TYPE: landslide | DATE: 2023-08-14
SATELLITE SOURCE: Sentinel-1 InSAR (Coherence + Displacement)

ZONE PRIORITY RANKINGS (calculated from satellite + infrastructure data):

Rank 1: Shimla
  Priority Score: 0.91/1.0
  Population Affected: 63,400
  Hospitals in Impact Zone: 3
  Schools in Impact Zone: 18
  Bridges at Risk: 5
  Road Accessibility: 34% of roads passable
  Detection Confidence: 85%

Rank 2: Kullu
  Priority Score: 0.79/1.0
  Population Affected: 41,200
  Hospitals in Impact Zone: 2
  Schools in Impact Zone: 12
  Bridges at Risk: 4
  Road Accessibility: 47% of roads passable
  Detection Confidence: 81%

Rank 3: Mandi
  Priority Score: 0.55/1.0
  Population Affected: 22,900
  Hospitals in Impact Zone: 1
  Schools in Impact Zone: 8
  Bridges at Risk: 2
  Road Accessibility: 61% of roads passable
  Detection Confidence: 74%
""",

    "odisha-cyclone-2023": """\
DISASTER EVENT: Cyclone Odisha 2023 | TYPE: cyclone | DATE: 2023-05-11
SATELLITE SOURCE: INSAT-3D (IR + Water Vapour, Dvorak Technique)

ZONE PRIORITY RANKINGS (calculated from satellite + infrastructure data):

Rank 1: Puri
  Priority Score: 0.93/1.0
  Population Affected: 251,000
  Hospitals in Impact Zone: 7
  Schools in Impact Zone: 34
  Bridges at Risk: 3
  Road Accessibility: 42% of roads passable
  Storm Surge Estimate: 2.1 m
  Detection Confidence: 88%

Rank 2: Ganjam
  Priority Score: 0.85/1.0
  Population Affected: 318,700
  Hospitals in Impact Zone: 9
  Schools in Impact Zone: 41
  Bridges at Risk: 2
  Road Accessibility: 50% of roads passable
  Storm Surge Estimate: 1.4 m
  Detection Confidence: 84%

Rank 3: Khordha
  Priority Score: 0.66/1.0
  Population Affected: 189,400
  Hospitals in Impact Zone: 5
  Schools in Impact Zone: 26
  Bridges at Risk: 1
  Road Accessibility: 64% of roads passable
  Storm Surge Estimate: 0.8 m
  Detection Confidence: 80%
""",

    "gujarat-earthquake-2024": """\
DISASTER EVENT: Gujarat Earthquake 2024 | TYPE: earthquake | DATE: 2024-03-21
SATELLITE SOURCE: Sentinel-1 D-InSAR (Co-seismic Displacement Stack)

ZONE PRIORITY RANKINGS (calculated from satellite + infrastructure data):

Rank 1: Kachchh
  Priority Score: 0.90/1.0
  Population Affected: 97,800
  Hospitals in Impact Zone: 4
  Schools in Impact Zone: 19
  Bridges at Risk: 6
  Road Accessibility: 40% of roads passable
  Peak Ground Acceleration: 0.38g (USGS ShakeMap)
  Detection Confidence: 82%

Rank 2: Morbi
  Priority Score: 0.68/1.0
  Population Affected: 54,200
  Hospitals in Impact Zone: 2
  Schools in Impact Zone: 11
  Bridges at Risk: 3
  Road Accessibility: 57% of roads passable
  Peak Ground Acceleration: 0.21g (USGS ShakeMap)
  Detection Confidence: 77%

Rank 3: Jamnagar
  Priority Score: 0.49/1.0
  Population Affected: 31,600
  Hospitals in Impact Zone: 1
  Schools in Impact Zone: 6
  Bridges at Risk: 1
  Road Accessibility: 71% of roads passable
  Peak Ground Acceleration: 0.14g (USGS ShakeMap)
  Detection Confidence: 71%
""",
}

# Fallback for unknown event IDs — generic minimal block so the copilot
# always has something to work with and never errors due to missing context.
_DEMO_CONTEXT_FALLBACK = """\
DISASTER EVENT: Active Emergency | TYPE: unknown | DATE: current
SATELLITE SOURCE: Multi-source satellite composite

No detailed zone data is available for this event yet.
Analysis may still be processing.
"""

# ── System prompt template ────────────────────────────────────────────────────
_SYSTEM_PROMPT_TEMPLATE = """\
You are the OrbitalMind EO Decision Copilot.
You assist emergency managers during active disaster response.

You have access to this verified satellite analysis data:
{context_text}

Currently selected zone: {active_zone}

YOUR STRICT RULES:
1. Answer in 2-3 sentences maximum. Be operational and direct.
2. Use ONLY the data provided above. If something is not in the data, say:
   "That information is not in the current analysis data."
3. Do NOT use bullet points, markdown, or formatting. Plain sentences only.
4. For evacuation/response recommendations, cite the specific metric
   from the data that supports the recommendation.

MAP COMMAND RULES (append to your reply when relevant):
- If the user asks to zoom, go to, show, navigate, or focus on a location:
  Append on a new line: MAP_ACTION::ZOOM::{{exact_zone_name_from_data}}
- If the user asks to show or highlight hospitals, roads, schools, or bridges:
  Append on a new line: MAP_ACTION::HIGHLIGHT::{{layer_name}}
- Only output a MAP_ACTION if the zone/layer name exists in your data above.
- Do not explain the MAP_ACTION tag in your reply text.\
"""


class CopilotService:
    """EO Conversational Copilot — database-grounded disaster Q&A.

    All public methods are ``async`` so they integrate cleanly with FastAPI
    endpoints without blocking the event loop.
    """

    # ── Context builder ───────────────────────────────────────────────────────

    async def build_context_text(self, event_id: str, disaster_type: str) -> str:
        """Return a structured plain-text context block for the given event.

        In DEMO_MODE the block is served from in-memory fixtures (<1 ms).
        In live mode a PostGIS query is executed via asyncpg.

        Parameters
        ----------
        event_id:
            The canonical event identifier (e.g. ``"kerala-2018"``).
        disaster_type:
            Disaster category string (e.g. ``"flood"``).

        Returns
        -------
        str
            Multi-line context block ready to embed in the system prompt.
        """
        if settings.DEMO_MODE:
            return self._build_demo_context(event_id, disaster_type)
        return await self._build_live_context(event_id, disaster_type)

    def _build_demo_context(self, event_id: str, disaster_type: str) -> str:  # noqa: ARG002
        """Return hardcoded context for a known demo event_id."""
        # Normalise common event-ID variants
        normalised = event_id.lower().replace("_", "-")
        ctx = _DEMO_CONTEXTS.get(normalised) or _DEMO_CONTEXTS.get(event_id)
        if ctx:
            return ctx

        # Partial key match (e.g. "kerala" matches "kerala-2018")
        for key, value in _DEMO_CONTEXTS.items():
            if normalised in key or key in normalised:
                return value

        logger.warning("No demo context found for event_id=%r; using fallback.", event_id)
        return _DEMO_CONTEXT_FALLBACK

    async def _build_live_context(self, event_id: str, disaster_type: str) -> str:  # noqa: ARG002
        """Query priority_results + admin_zones via asyncpg and format context.

        Requires the DATABASE_URL to point at a live PostGIS instance with
        the priority_results and disaster_events tables populated.
        """
        try:
            import asyncpg  # type: ignore[import-untyped]

            dsn = settings.asyncpg_dsn
            conn: asyncpg.Connection = await asyncio.wait_for(
                asyncpg.connect(dsn), timeout=5.0
            )
            try:
                rows = await conn.fetch(
                    """
                    SELECT
                        pr.zone_id,
                        COALESCE(az.zone_name, pr.zone_id)  AS zone_name,
                        pr.priority_rank,
                        pr.priority_score,
                        pr.pop_affected,
                        pr.hospitals,
                        pr.schools,
                        pr.bridges,
                        pr.road_pct,
                        pr.confidence,
                        de.event_name,
                        de.disaster_type,
                        de.date_start,
                        de.data_source
                    FROM priority_results pr
                    LEFT JOIN admin_zones az ON az.zone_id = pr.zone_id
                    JOIN disaster_events de ON de.event_id = pr.event_id
                    WHERE pr.event_id = $1
                    ORDER BY pr.priority_rank ASC
                    LIMIT 15
                    """,
                    event_id,
                )
            finally:
                await conn.close()

            if not rows:
                logger.warning("No priority_results found for event_id=%r.", event_id)
                return _DEMO_CONTEXT_FALLBACK

            # Build header from first row
            r0 = rows[0]
            lines: list[str] = [
                f"DISASTER EVENT: {r0['event_name']} | TYPE: {r0['disaster_type']}"
                f" | DATE: {r0['date_start']}",
                f"SATELLITE SOURCE: {r0['data_source'] or 'Satellite composite'}",
                "",
                "ZONE PRIORITY RANKINGS (calculated from satellite + infrastructure data):",
                "",
            ]

            for r in rows:
                lines += [
                    f"Rank {r['priority_rank']}: {r['zone_name']}",
                    f"  Priority Score: {r['priority_score']:.2f}/1.0",
                    f"  Population Affected: {r['pop_affected']:,}",
                    f"  Hospitals in Impact Zone: {r['hospitals']}",
                    f"  Schools in Impact Zone: {r['schools']}",
                    f"  Bridges at Risk: {r['bridges']}",
                    f"  Road Accessibility: {r['road_pct']:.0f}% of roads passable",
                    f"  Detection Confidence: {r['confidence']:.0%}",
                    "",
                ]

            return "\n".join(lines)

        except Exception as exc:  # noqa: BLE001
            logger.error("Live context query failed: %s — falling back to demo.", exc)
            return self._build_demo_context(event_id, disaster_type)

    # ── MAP_ACTION parser ─────────────────────────────────────────────────────

    async def parse_map_commands(
        self, text: str
    ) -> tuple[str, dict[str, Any] | None]:
        """Extract and strip MAP_ACTION tags from LLM reply text.

        Parameters
        ----------
        text:
            Raw LLM response that may contain ``MAP_ACTION::...`` lines.

        Returns
        -------
        tuple[str, dict | None]
            ``(clean_text, map_action_dict)`` where ``clean_text`` has all
            MAP_ACTION lines removed and ``map_action_dict`` is either a
            structured action or ``None`` if no action was found.

        Supported tag formats
        ----------------------
        ``MAP_ACTION::ZOOM::{zone_name}``
            → ``{"action": "ZOOM", "target": zone_name}``
        ``MAP_ACTION::HIGHLIGHT::{layer}``
            → ``{"action": "HIGHLIGHT", "layer": layer.strip()}``
        """
        match = _MAP_ACTION_RE.search(text)
        if not match:
            return text.strip(), None

        action_type = match.group("action").upper()
        target_raw  = match.group("target").strip()

        # Strip the entire MAP_ACTION line from the reply
        clean_text = _MAP_ACTION_RE.sub("", text).strip()
        # Remove any trailing blank lines produced by the strip
        clean_text = re.sub(r"\n{3,}", "\n\n", clean_text).strip()

        if action_type == "ZOOM":
            map_action: dict[str, Any] = {"action": "ZOOM", "target": target_raw}
        elif action_type == "HIGHLIGHT":
            map_action = {"action": "HIGHLIGHT", "layer": target_raw.lower()}
        else:
            # Unknown action — log and return None so the UI ignores it safely
            logger.warning("Unknown MAP_ACTION type: %r — discarding.", action_type)
            return clean_text, None

        return clean_text, map_action

    # ── Main entry point ──────────────────────────────────────────────────────

    async def query_copilot(
        self,
        message:      str,
        event_id:     str,
        disaster_type: str,
        active_zone:  str | None,
    ) -> dict[str, Any]:
        """Run a full copilot query cycle: context → prompt → LLM → parse.

        Parameters
        ----------
        message:
            The emergency manager's question (plain English, max 500 chars).
        event_id:
            Active event identifier — used to fetch the context block.
        disaster_type:
            Active disaster module type (for system prompt context).
        active_zone:
            Currently selected zone name in the map UI, or None.

        Returns
        -------
        dict
            ``reply``       — clean LLM text (MAP_ACTION tags removed)
            ``map_action``  — structured command dict or None
            ``event_id``    — echoed back for frontend routing
            ``disaster_type`` — echoed back
        """
        context_text = await self.build_context_text(event_id, disaster_type)

        system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(
            context_text=context_text,
            active_zone=active_zone or "None selected",
        )

        base_response = {
            "reply":        "",
            "map_action":   None,
            "event_id":     event_id,
            "disaster_type": disaster_type,
        }

        try:
            raw_reply: str = await asyncio.wait_for(
                self._call_ollama(system_prompt, message),
                timeout=12.0,
            )
        except asyncio.TimeoutError:
            logger.warning("Ollama response timed out for event_id=%r.", event_id)
            base_response["reply"] = (
                "Response timed out. Please try again."
            )
            return base_response
        except Exception as exc:  # noqa: BLE001
            logger.error("Ollama call failed: %s", exc)
            base_response["reply"] = (
                "AI assistant unavailable. Check that Ollama is running with: "
                "ollama serve"
            )
            return base_response

        clean_reply, map_action = await self.parse_map_commands(raw_reply)
        base_response["reply"]      = clean_reply
        base_response["map_action"] = map_action
        return base_response

    @staticmethod
    async def _call_ollama(system_prompt: str, user_message: str) -> str:
        """Async wrapper around the synchronous ollama.chat() call.

        Runs in the default executor to avoid blocking the event loop,
        which matters during concurrent copilot requests.
        """
        loop = asyncio.get_running_loop()

        def _sync_call() -> str:
            response = ollama.chat(
                model=settings.OLLAMA_MODEL,
                messages=[
                    {"role": "system",  "content": system_prompt},
                    {"role": "user",    "content": user_message},
                ],
                options={
                    "temperature": 0.3,   # low temperature = factual, not creative
                    "num_predict": 200,   # 2-3 sentences ≈ 60-100 tokens; cap at 200
                },
            )
            return response["message"]["content"]

        return await loop.run_in_executor(None, _sync_call)
