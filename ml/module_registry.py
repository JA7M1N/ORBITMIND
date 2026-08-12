"""
OrbitalMind — Disaster Module Registry
=======================================
Central lookup table mapping disaster_type strings → DisasterModule instances.

Usage
-----
    from ml.module_registry import get_module, list_modules, DISASTER_MODULES

    # Get a specific module
    flood = get_module("flood")
    result = flood.get_demo_data("kerala_2018")

    # List all modules (used by GET /api/modules endpoint)
    modules = list_modules()
    # → [{'disaster_type': 'flood', 'display_name': 'Flood Detection', ...}, ...]

    # Direct dict access (when you already know the type is valid)
    module = DISASTER_MODULES["wildfire"]

Startup validation
------------------
On import the registry calls ``validate_weights()`` on every module.
A misconfigured ``priority_weights`` dict (sum ≠ 1.0) raises ``ValueError``
immediately rather than producing silent scoring errors at runtime.
"""

from __future__ import annotations

from typing import Any

from ml.disaster_module import DisasterModule
from ml.modules.flood_module import FloodModule
from ml.modules.wildfire_module import WildfireModule
from ml.modules.landslide_module import LandslideModule
from ml.modules.cyclone_module import CycloneModule
from ml.modules.earthquake_module import EarthquakeModule

# ---------------------------------------------------------------------------
# Module instances
# ---------------------------------------------------------------------------

_flood      = FloodModule()
_wildfire   = WildfireModule()
_landslide  = LandslideModule()
_cyclone    = CycloneModule()
_earthquake = EarthquakeModule()

# ---------------------------------------------------------------------------
# Registry — single source of truth for all disaster modules
# ---------------------------------------------------------------------------

DISASTER_MODULES: dict[str, DisasterModule] = {
    "flood":      _flood,
    "wildfire":   _wildfire,
    "landslide":  _landslide,
    "cyclone":    _cyclone,
    "earthquake": _earthquake,
}
"""
Mapping of ``disaster_type`` string  →  ``DisasterModule`` singleton instance.

All five entries are instantiated once at import time and shared across the
entire FastAPI application lifetime (thread-safe for reads).
"""

# ---------------------------------------------------------------------------
# Startup validation — fail fast on misconfigured weights
# ---------------------------------------------------------------------------

def _validate_all() -> None:
    """Validate ``priority_weights`` for every registered module.

    Called automatically when this module is imported.
    Raises ``ValueError`` immediately if any module's weights are misconfigured,
    so errors surface at startup rather than silently corrupting scores later.

    Raises
    ------
    ValueError
        If any module's ``priority_weights`` do not sum to 1.0 (±0.01).
    """
    for disaster_type, module in DISASTER_MODULES.items():
        try:
            module.validate_weights()
        except ValueError as exc:
            raise ValueError(
                f"Registry validation failed for module '{disaster_type}': {exc}"
            ) from exc


_validate_all()

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_module(disaster_type: str) -> DisasterModule:
    """Return the ``DisasterModule`` instance for the given disaster type.

    Parameters
    ----------
    disaster_type : str
        Case-sensitive disaster type key (one of: ``"flood"``, ``"wildfire"``,
        ``"landslide"``, ``"cyclone"``, ``"earthquake"``).

    Returns
    -------
    DisasterModule
        The registered module singleton for the requested disaster type.

    Raises
    ------
    ValueError
        If ``disaster_type`` is not registered in ``DISASTER_MODULES``.

    Examples
    --------
    >>> module = get_module("flood")
    >>> module.display_name
    'Flood Detection'

    >>> get_module("tornado")
    ValueError: Unknown disaster type: 'tornado'.
    Valid types: flood, wildfire, landslide, cyclone, earthquake
    """
    module = DISASTER_MODULES.get(disaster_type)
    if module is None:
        valid = ", ".join(DISASTER_MODULES.keys())
        raise ValueError(
            f"Unknown disaster type: '{disaster_type}'.\n"
            f"Valid types: {valid}"
        )
    return module


def list_modules() -> list[dict[str, Any]]:
    """Return metadata for all registered disaster modules.

    Used by the ``GET /api/modules`` FastAPI endpoint to populate the
    frontend ``DisasterNav`` module switcher.

    Returns
    -------
    list[dict]
        One dict per module, ordered by ``DISASTER_MODULES`` insertion order
        (flood → wildfire → landslide → cyclone → earthquake).
        Each dict is the output of ``DisasterModule.get_module_info()``.

    Examples
    --------
    >>> modules = list_modules()
    >>> len(modules)
    5
    >>> modules[0]['disaster_type']
    'flood'
    >>> modules[0]['status']
    'live'
    """
    return [module.get_module_info() for module in DISASTER_MODULES.values()]
