"""
OrbitalMind — Copilot Suggestion Chips
========================================
Default prompt suggestions shown to emergency managers before they type.

Each suggestion is phrased as a question an incident commander would
plausibly ask during an active response — not a generic chatbot prompt.
The frontend renders these as clickable chips in the copilot panel;
clicking one submits it as the first message.

Usage
-----
    from backend.data.copilot_suggestions import SUGGESTIONS

    chips = SUGGESTIONS.get(disaster_type, SUGGESTIONS["flood"])
"""
from __future__ import annotations

SUGGESTIONS: dict[str, list[str]] = {
    "flood": [
        "Which district should receive rescue boats first?",
        "How many hospitals have lost road access?",
        "Draft an emergency alert for the highest priority zone.",
    ],
    "wildfire": [
        "Which villages are in the direct fire path?",
        "Which hospitals are near the fire perimeter?",
        "Draft an evacuation order for the highest risk zone.",
    ],
    "landslide": [
        "Which roads are completely blocked by debris?",
        "Which areas have the least accessible rescue routes?",
        "Draft a road closure advisory for the affected districts.",
    ],
    "cyclone": [
        "Which coastal villages need immediate evacuation?",
        "What is the storm surge risk for the highest ranked zone?",
        "Draft a coastal evacuation advisory.",
    ],
    "earthquake": [
        "Which hospitals are structurally at risk?",
        "Where is the highest concentration of building damage?",
        "Draft an emergency shelter advisory for the affected zones.",
    ],
}

# Ordered list matching SUPPORTED_DISASTERS in config.py —
# used by the suggestions endpoint for consistent default ordering.
DEFAULT_DISASTER_ORDER: list[str] = [
    "flood",
    "wildfire",
    "landslide",
    "cyclone",
    "earthquake",
]
