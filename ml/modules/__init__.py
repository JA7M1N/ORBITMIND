"""
OrbitalMind — Disaster Module Implementations
=============================================
Each module subclasses ``DisasterModule`` from ``ml.disaster_module``.

Modules
-------
flood_module      → FloodModule      (LIVE  — Attention U-Net)
wildfire_module   → WildfireModule   (DEMO  — NBR ratio mock)
landslide_module  → LandslideModule  (DEMO  — SAR+DEM mock)
cyclone_module    → CycloneModule    (DEMO  — storm surge mock)
earthquake_module → EarthquakeModule (DEMO  — InSAR coherence mock)
"""

from ml.modules.flood_module import FloodModule
from ml.modules.wildfire_module import WildfireModule
from ml.modules.landslide_module import LandslideModule
from ml.modules.cyclone_module import CycloneModule
from ml.modules.earthquake_module import EarthquakeModule

__all__ = [
    "FloodModule",
    "WildfireModule",
    "LandslideModule",
    "CycloneModule",
    "EarthquakeModule",
]
