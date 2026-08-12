"""
OrbitalMind — Flood Detection Module (LIVE)
============================================
Detection pipeline:
  GEE Sentinel-1 SAR download  →  VV/VH change detection  →
  Attention U-Net segmentation  →  SRTM slope mask  →
  Priority zone GeoJSON

VRAM budget: ~2.0 GB during U-Net inference (FP16, batch 8).
VRAM rule: GPU is cleared at the end of run_detection() so Ollama
           can be loaded immediately after without OOM.

Demo event: Kerala 2018 Floods
  bbox: [76.0, 9.5, 77.5, 11.0]
  date: 2018-08-01 → 2018-08-20
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from ml.disaster_module import DisasterModule

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[2]          # OrbitalMind/
_DEMO_BASE  = _REPO_ROOT / "backend" / "demo_data" / "flood"
_DATA_DIR   = _REPO_ROOT / "data"
_CKPT_PATH  = _REPO_ROOT / "checkpoints" / "flood_unet_best.pt"


class FloodModule(DisasterModule):
    """Live flood-detection module using Sentinel-1 SAR + Attention U-Net.

    Status
    ------
    **LIVE** — real ML inference via GEE + PyTorch.

    The module fetches pre-event / post-event Sentinel-1 GRD imagery from
    Google Earth Engine, computes a VV/VH change ratio, then passes the
    two-band stack (256×256 chips) through an Attention U-Net with an
    EfficientNet-B0 encoder.

    FP16 mixed precision (``torch.cuda.amp``) keeps peak VRAM ≤ 2.0 GB on
    an RTX 3050 (4 GB).  GPU memory is explicitly freed at the end of
    ``run_detection()`` so the LLM service can load Ollama immediately after.

    Priority weights (from OrbitalMind architecture spec)
    -----------------------------------------------------
    population  0.40  ← highest weight — dense settlements drive priority
    infra       0.30  ← hospitals, schools, bridges
    access      0.20  ← intact roads ratio
    intensity   0.10  ← SAR backscatter change magnitude
    """

    # ------------------------------------------------------------------ #
    # Module metadata                                                      #
    # ------------------------------------------------------------------ #
    disaster_type    : str        = "flood"
    display_name     : str        = "Flood Detection"
    icon             : str        = "🌊"
    color            : str        = "#1e40af"
    satellite_sources: list[str]  = [
        "COPERNICUS/S1_GRD",                # Sentinel-1 SAR (primary)
        "COPERNICUS/S2_SR_HARMONIZED",      # Sentinel-2 optical (cloud mask)
        "USGS/SRTMGL1_003",                 # SRTM DEM (slope / hand)
    ]
    detection_method : str = (
        "Sentinel-1 SAR VV/VH change detection + Attention U-Net segmentation"
    )
    affected_infra_types: list[str] = [
        "hospital",
        "school",
        "bridge",
        "highway",
    ]
    priority_weights: dict[str, float] = {
        "population": 0.40,
        "infra":      0.30,
        "access":     0.20,
        "intensity":  0.10,
    }
    is_live       : bool = True
    demo_event_id : str  = "kerala_2018"

    # ------------------------------------------------------------------ #
    # Demo data loader                                                     #
    # ------------------------------------------------------------------ #

    def get_demo_data(self, event_id: str = "kerala_2018") -> dict[str, Any]:
        """Load pre-generated flood mask from disk (DEMO_MODE=True).

        Reads ``backend/demo_data/flood/kerala_2018/flood_mask.geojson``
        and returns the standardised OrbitalMind response dict.

        This path requires no GPU, no GEE API call, and responds in <100 ms.

        Parameters
        ----------
        event_id : str
            Demo event slug. Defaults to ``"kerala_2018"`` (the canonical
            flood demo). Other slugs are forwarded as sub-directory names.

        Returns
        -------
        dict
            Standardised response containing ``affected_zones`` GeoJSON and
            ``summary_stats``.

        Raises
        ------
        FileNotFoundError
            If ``flood_mask.geojson`` is absent from the expected directory.
        """
        geojson_path = _DEMO_BASE / event_id / "flood_mask.geojson"
        if not geojson_path.exists():
            raise FileNotFoundError(
                f"Flood demo data not found at: {geojson_path}\n"
                "Run scripts/gee_data_pull.py then ml/inference/flood_inference.py "
                "to generate the demo GeoJSON."
            )

        with geojson_path.open("r", encoding="utf-8") as fh:
            geojson = json.load(fh)

        # Compute summary stats from feature properties
        features   = geojson.get("features", [])
        total_area = sum(f["properties"].get("area_km2", 0.0) for f in features)
        confidences = [
            f["properties"].get("confidence", 0.0)
            for f in features
            if "confidence" in f.get("properties", {})
        ]
        mean_conf = sum(confidences) / len(confidences) if confidences else 0.0

        return {
            "event_id":       event_id,
            "disaster_type":  self.disaster_type,
            "source":         "demo",
            "affected_zones": geojson,
            "summary_stats":  {
                "total_area_km2":  round(total_area, 2),
                "mean_confidence": round(mean_conf, 4),
                "peak_intensity":  1.0,
                "tiles_processed": None,
                "used_otsu":       False,
            },
        }

    # ------------------------------------------------------------------ #
    # Live detection                                                        #
    # ------------------------------------------------------------------ #

    def run_detection(
        self,
        event_id: str,
        bbox: list[float],
        date_range: tuple[str, str],
    ) -> dict[str, Any]:
        """Run live Sentinel-1 + Attention U-Net flood detection.

        Full pipeline:
        1. Pull Sentinel-1 pre/during composites from GEE (5×5 boxcar filtered)
        2. Pull SRTM DEM for the bbox
        3. Run the full inference pipeline (tile → U-Net → stitch → slope mask)
        4. Return standardised OrbitalMind result dict
        5. Clear GPU VRAM (VRAM rule: Ollama loads next)

        .. warning::
            **VRAM rule**: Do NOT load Ollama while this method is running.
            This method calls ``torch.cuda.empty_cache()`` on completion so
            the LLM service can immediately load the 3B model.

        Parameters
        ----------
        event_id : str
            UUID of the ``disaster_events`` row for this analysis run.
            Also used as the output subdirectory name under ``data/``.
        bbox : list[float]
            ``[min_lon, min_lat, max_lon, max_lat]`` in EPSG:4326.
            Kerala demo: ``[76.0, 9.5, 77.5, 11.0]``.
        date_range : tuple[str, str]
            ISO-8601 start/end dates of the **during-flood** period.
            Pre-flood dates are derived automatically as 60 days before start.
            Example: ``("2018-08-01", "2018-08-20")``.

        Returns
        -------
        dict
            Standardised OrbitalMind detection response::

                {
                    "event_id":      str,
                    "disaster_type": "flood",
                    "source":        "unet_inference",
                    "affected_zones": <GeoJSON FeatureCollection>,
                    "summary_stats": {
                        "total_area_km2":  float,
                        "mean_confidence": float,
                        "peak_intensity":  float,
                        "tiles_processed": int,
                        "used_otsu":       bool,
                    },
                }

        Raises
        ------
        RuntimeError
            If GEE authentication fails, imagery is unavailable, or VRAM
            is insufficient for the inference batch.
        ImportError
            If required ML dependencies are not installed.
        """
        # Lazy imports (ML deps may not be installed in demo-only deploys)
        import torch
        from scripts.gee_data_pull import (
            authenticate_gee,
            bbox_to_ee_region,
            get_sentinel1_composite,
            get_srtm_dem,
            download_composite,
            _download_band,
        )
        from ml.inference.flood_inference import run_flood_inference
        from datetime import date, timedelta

        # ---------------------------------------------------------------- #
        # 1. Set up working directory for this event                       #
        # ---------------------------------------------------------------- #
        event_data_dir = _DATA_DIR / event_id
        event_data_dir.mkdir(parents=True, exist_ok=True)

        # ---------------------------------------------------------------- #
        # 2. Compute pre-flood date window (60 days before flood start)    #
        # ---------------------------------------------------------------- #
        flood_start = date.fromisoformat(date_range[0])
        flood_end   = date.fromisoformat(date_range[1])
        pre_start   = flood_start - timedelta(days=60)
        pre_end     = flood_start - timedelta(days=1)

        print(f"[FLOOD] Pre-flood period : {pre_start} → {pre_end}")
        print(f"[FLOOD] During-flood     : {flood_start} → {flood_end}")

        # ---------------------------------------------------------------- #
        # 3. Download SAR data from GEE                                    #
        # ---------------------------------------------------------------- #
        authenticate_gee()
        import ee  # type: ignore[import]

        region = bbox_to_ee_region(bbox)

        pre_path    = event_data_dir / "s1_pre_flood.tif"
        during_path = event_data_dir / "s1_during_flood.tif"
        dem_path    = event_data_dir / "srtm_dem.tif"

        if not pre_path.exists():
            pre_composite = get_sentinel1_composite(
                region,
                str(pre_start),
                str(pre_end),
                label=f"Pre-flood ({pre_start}→{pre_end})",
            )
            download_composite(
                image=pre_composite,
                region=region,
                scale=30,
                bands=["VV", "VH"],
                output_path=pre_path,
            )

        if not during_path.exists():
            during_composite = get_sentinel1_composite(
                region,
                str(flood_start),
                str(flood_end),
                label=f"During-flood ({flood_start}→{flood_end})",
            )
            download_composite(
                image=during_composite,
                region=region,
                scale=30,
                bands=["VV", "VH"],
                output_path=during_path,
            )

        if not dem_path.exists():
            import ee  # already imported above, guard for clarity
            dem_image = get_srtm_dem(region)
            _download_band(dem_image, "elevation", region, scale=30, output_path=dem_path)

        # ---------------------------------------------------------------- #
        # 4. Run ML inference pipeline                                     #
        # ---------------------------------------------------------------- #
        demo_out_dir = _DEMO_BASE / event_id
        result = run_flood_inference(
            pre_path     = pre_path,
            during_path  = during_path,
            dem_path     = dem_path,
            output_dir   = event_data_dir,
            model_path   = _CKPT_PATH if _CKPT_PATH.exists() else None,
            batch_size   = 8,
            demo_out_dir = demo_out_dir,
        )

        # ---------------------------------------------------------------- #
        # 5. VRAM rule — clear GPU memory                                  #
        # ---------------------------------------------------------------- #
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            print("[VRAM] GPU memory cleared — Ollama can now be loaded")

        result["event_id"] = event_id
        return result
