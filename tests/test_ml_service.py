"""
OrbitalMind — ML Service Tests
================================
Tests the MLService layer end-to-end against real demo data on disk.

Requirements
------------
- backend/demo_data/ must be populated (run: python scripts/generate_mock_data.py)
- No GPU, GEE credentials, or internet connection required.

Run
---
    pytest tests/test_ml_service.py -v

Test inventory
--------------
  test_all_modules_returned               5 modules in get_available_modules()
  test_module_fields_complete             All DisasterModuleInfo fields present
  test_module_weights_sum_to_one          Priority weights sum to 1.0 for each
  test_demo_returns_under_500ms           Kerala flood demo completes in <500ms
  test_demo_event_id_hyphen_normalised    "kerala-2018" handled same as "kerala_2018"
  test_returned_geojson_is_feature_collection  GeoJSON type check
  test_returned_geojson_has_features      At least 1 feature returned
  test_all_features_have_valid_geometry   Geometry type is a known GeoJSON type
  test_confidence_range_flood             All flood confidences ∈ [0, 1]
  test_confidence_range_all_modules       All 5 modules' demo data confidences valid
  test_get_event_stats_flood              Flood stats keys and value ranges
  test_get_event_stats_wildfire           Wildfire: high_severity_pct ∈ [0, 100]
  test_get_event_stats_cyclone            Cyclone: max_wind_speed_kmh > 0
  test_get_event_stats_earthquake         Earthquake: destroyed_pct ∈ [0, 100]
  test_live_non_flood_returns_task_id     Task ID returned immediately
  test_live_non_flood_status_is_error     Status is 'error' (no 500 raised)
  test_live_non_flood_error_has_module    Error dict contains 'module' key
  test_live_non_flood_error_message_phase2 Error message mentions Phase 2
  test_unknown_disaster_type_raises       ValueError for unknown type
  test_unknown_task_id_raises             KeyError for unknown task_id
"""

from __future__ import annotations

import time
from typing import Any

import pytest

# conftest.py adds the repo root to sys.path before this module is imported.
from backend.services.ml_service import MLService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def svc() -> MLService:
    """Single MLService instance shared across all tests in this module."""
    return MLService()


@pytest.fixture(scope="module")
def kerala_result(svc: MLService) -> dict[str, Any]:
    """Pre-loaded Kerala 2018 flood demo result (shared across tests)."""
    return svc.run_detection_demo("kerala_2018", "flood")


@pytest.fixture(scope="module")
def all_modules(svc: MLService) -> list[dict[str, Any]]:
    """Pre-loaded module list (shared across tests)."""
    return svc.get_available_modules()


# ---------------------------------------------------------------------------
# MODULE LISTING TESTS
# ---------------------------------------------------------------------------

class TestGetAvailableModules:
    """get_available_modules() — module metadata correctness."""

    def test_all_modules_returned(self, all_modules: list[dict]) -> None:
        """Exactly 5 modules must be registered."""
        assert len(all_modules) == 5, (
            f"Expected 5 modules, got {len(all_modules)}"
        )

    def test_disaster_types_complete(self, all_modules: list[dict]) -> None:
        """All 5 expected disaster types are present."""
        types = {m["disaster_type"] for m in all_modules}
        expected = {"flood", "wildfire", "landslide", "cyclone", "earthquake"}
        assert types == expected, f"Missing types: {expected - types}"

    def test_module_fields_complete(self, all_modules: list[dict]) -> None:
        """Every module dict contains all required metadata fields."""
        required_fields = {
            "disaster_type", "display_name", "icon", "color", "status",
            "is_live", "demo_event_id", "satellite_sources",
            "detection_method", "affected_infra_types",
            "priority_weights", "description",
        }
        for mod in all_modules:
            missing = required_fields - mod.keys()
            assert not missing, (
                f"Module '{mod.get('disaster_type')}' missing fields: {missing}"
            )

    def test_module_weights_sum_to_one(self, all_modules: list[dict]) -> None:
        """Priority weights must sum to 1.0 (±0.01) for every module."""
        for mod in all_modules:
            w    = mod["priority_weights"]
            total = w["population"] + w["infra"] + w["access"] + w["intensity"]
            assert abs(total - 1.0) <= 0.01, (
                f"Module '{mod['disaster_type']}' weights sum to {total:.4f}"
            )

    def test_flood_is_live_others_are_demo(self, all_modules: list[dict]) -> None:
        """Only Flood module has status='live'; all others are 'demo'."""
        for mod in all_modules:
            if mod["disaster_type"] == "flood":
                assert mod["status"] == "live",  "Flood must be live"
                assert mod["is_live"] is True,   "Flood is_live must be True"
            else:
                assert mod["status"] == "demo",  f"{mod['disaster_type']} must be demo"
                assert mod["is_live"] is False,  f"{mod['disaster_type']} is_live must be False"

    def test_descriptions_are_non_empty(self, all_modules: list[dict]) -> None:
        """Every module must have a non-empty description string."""
        for mod in all_modules:
            desc = mod.get("description", "")
            assert isinstance(desc, str) and len(desc) > 10, (
                f"Module '{mod['disaster_type']}' has empty/short description"
            )

    def test_icon_is_emoji(self, all_modules: list[dict]) -> None:
        """Icon field must be a single non-ASCII character (emoji)."""
        for mod in all_modules:
            icon = mod["icon"]
            assert len(icon) >= 1 and not icon.isascii(), (
                f"Module '{mod['disaster_type']}' icon '{icon}' doesn't look like emoji"
            )

    def test_color_is_hex(self, all_modules: list[dict]) -> None:
        """Color must be a hex string starting with '#'."""
        for mod in all_modules:
            color = mod["color"]
            assert color.startswith("#") and len(color) in (4, 7), (
                f"Module '{mod['disaster_type']}' color '{color}' is not valid hex"
            )


# ---------------------------------------------------------------------------
# DEMO DETECTION TESTS
# ---------------------------------------------------------------------------

class TestRunDetectionDemo:
    """run_detection_demo() — correctness, speed, and GeoJSON structure."""

    def test_demo_returns_under_500ms(self, svc: MLService) -> None:
        """Demo read must complete in < 500 ms (disk-only, no GPU)."""
        t0     = time.perf_counter()
        result = svc.run_detection_demo("kerala_2018", "flood")
        elapsed = time.perf_counter() - t0
        assert elapsed < 0.5, (
            f"Demo too slow: {elapsed:.3f}s (expected < 0.5s). "
            "Ensure demo data exists: python scripts/generate_mock_data.py"
        )

    def test_demo_event_id_hyphen_normalised(self, svc: MLService) -> None:
        """'kerala-2018' (hyphen) must return the same result as 'kerala_2018'."""
        r1 = svc.run_detection_demo("kerala-2018",  "flood")
        r2 = svc.run_detection_demo("kerala_2018", "flood")
        assert r1["event_id"] == r2["event_id"]
        assert len(r1["affected_zones_geojson"]["features"]) == \
               len(r2["affected_zones_geojson"]["features"])

    def test_result_has_required_top_level_keys(self, kerala_result: dict) -> None:
        """Detection result must contain all required keys."""
        required = {
            "event_id", "disaster_type", "source",
            "affected_zones_geojson", "stats", "module_info",
        }
        missing = required - kerala_result.keys()
        assert not missing, f"Missing keys in result: {missing}"

    def test_returned_geojson_is_feature_collection(self, kerala_result: dict) -> None:
        """GeoJSON root must be a FeatureCollection."""
        geojson = kerala_result["affected_zones_geojson"]
        assert geojson["type"] == "FeatureCollection", (
            f"Expected FeatureCollection, got '{geojson.get('type')}'"
        )
        assert "features" in geojson, "GeoJSON must have 'features' key"

    def test_returned_geojson_has_features(self, kerala_result: dict) -> None:
        """FeatureCollection must contain at least 1 feature."""
        features = kerala_result["affected_zones_geojson"]["features"]
        assert len(features) >= 1, "Expected at least 1 flood feature"

    def test_all_features_have_valid_geometry_type(self, kerala_result: dict) -> None:
        """Every feature must have a valid GeoJSON geometry type."""
        valid_types = {
            "Point", "MultiPoint",
            "LineString", "MultiLineString",
            "Polygon", "MultiPolygon",
            "GeometryCollection",
        }
        features = kerala_result["affected_zones_geojson"]["features"]
        for i, feat in enumerate(features):
            geom = feat.get("geometry") or {}
            gtype = geom.get("type")
            assert gtype in valid_types, (
                f"Feature {i}: invalid geometry type '{gtype}'"
            )

    def test_all_features_have_coordinates(self, kerala_result: dict) -> None:
        """Every Polygon/LineString feature must have non-empty coordinates."""
        features = kerala_result["affected_zones_geojson"]["features"]
        for i, feat in enumerate(features):
            geom = feat.get("geometry") or {}
            if geom.get("type") in ("Polygon", "LineString", "MultiPolygon"):
                coords = geom.get("coordinates")
                assert coords, f"Feature {i} has empty coordinates"

    # --- Confidence value range tests ---

    def test_confidence_range_flood(self, kerala_result: dict) -> None:
        """All confidence values in the Kerala flood result must be in [0, 1]."""
        features = kerala_result["affected_zones_geojson"]["features"]
        for i, feat in enumerate(features):
            conf = feat["properties"].get("confidence")
            assert conf is not None, f"Feature {i} missing 'confidence'"
            assert isinstance(conf, (int, float)), (
                f"Feature {i}: confidence is not numeric: {conf!r}"
            )
            assert 0.0 <= conf <= 1.0, (
                f"Feature {i}: confidence {conf} outside [0, 1]"
            )

    @pytest.mark.parametrize("disaster_type,event_id", [
        ("flood",      "kerala_2018"),
        ("wildfire",   "uttarakhand_2024"),
        ("landslide",  "himachal_2023"),
        ("cyclone",    "odisha_2023"),
        ("earthquake", "gujarat_2024"),
    ])
    def test_confidence_range_all_modules(
        self, svc: MLService, disaster_type: str, event_id: str
    ) -> None:
        """All 5 demo modules must return confidence values ∈ [0, 1]."""
        result   = svc.run_detection_demo(event_id, disaster_type)
        features = result["affected_zones_geojson"]["features"]
        assert len(features) >= 1, f"{disaster_type}: expected at least 1 feature"
        for i, feat in enumerate(features):
            conf = feat["properties"].get("confidence")
            assert conf is not None, (
                f"{disaster_type} feature {i}: missing 'confidence' property"
            )
            assert 0.0 <= conf <= 1.0, (
                f"{disaster_type} feature {i}: confidence {conf} outside [0, 1]"
            )

    def test_module_info_embedded_in_result(self, kerala_result: dict) -> None:
        """module_info must be embedded and show disaster_type='flood'."""
        mi = kerala_result["module_info"]
        assert mi["disaster_type"] == "flood"
        assert mi["status"] == "live"

    def test_source_field_is_string(self, kerala_result: dict) -> None:
        """Source field must be a non-empty string."""
        src = kerala_result.get("source", "")
        assert isinstance(src, str) and len(src) > 0

    def test_stats_field_has_required_keys(self, kerala_result: dict) -> None:
        """Stats dict must have at minimum feature_count and avg_confidence."""
        stats = kerala_result["stats"]
        assert "feature_count"  in stats, "stats missing 'feature_count'"
        assert "avg_confidence" in stats, "stats missing 'avg_confidence'"

    def test_stats_feature_count_matches_geojson(self, kerala_result: dict) -> None:
        """stats.feature_count must equal len(features)."""
        n_features  = len(kerala_result["affected_zones_geojson"]["features"])
        stat_count  = kerala_result["stats"]["feature_count"]
        assert stat_count == n_features, (
            f"stats.feature_count={stat_count} != actual features={n_features}"
        )

    def test_unknown_disaster_type_raises_valueerror(self, svc: MLService) -> None:
        """Unknown disaster type must raise ValueError (not 500)."""
        with pytest.raises(ValueError, match="Unknown disaster type"):
            svc.run_detection_demo("kerala_2018", "tornado")


# ---------------------------------------------------------------------------
# EVENT STATS TESTS
# ---------------------------------------------------------------------------

class TestGetEventStats:
    """get_event_stats() — disaster-specific stat keys and value ranges."""

    def test_flood_stats_keys(self, svc: MLService) -> None:
        """Flood stats must include total_flooded_area_km2."""
        stats = svc.get_event_stats("kerala_2018", "flood")
        assert "total_flooded_area_km2" in stats, (
            "Flood stats missing 'total_flooded_area_km2'"
        )
        assert stats["total_flooded_area_km2"] >= 0.0

    def test_flood_avg_confidence_range(self, svc: MLService) -> None:
        """Flood avg_confidence must be in [0, 1]."""
        stats = svc.get_event_stats("kerala_2018", "flood")
        conf  = stats["avg_confidence"]
        assert 0.0 <= conf <= 1.0, f"avg_confidence={conf} outside [0, 1]"

    def test_wildfire_stats_keys(self, svc: MLService) -> None:
        """Wildfire stats must include total_burned_area_km2 and high_severity_pct."""
        stats = svc.get_event_stats("uttarakhand_2024", "wildfire")
        assert "total_burned_area_km2" in stats
        assert "high_severity_pct"     in stats
        assert 0.0 <= stats["high_severity_pct"] <= 100.0, (
            f"high_severity_pct={stats['high_severity_pct']} outside [0, 100]"
        )

    def test_landslide_stats_keys(self, svc: MLService) -> None:
        """Landslide stats must include total_slide_area_km2 and avg_slope_angle."""
        stats = svc.get_event_stats("himachal_2023", "landslide")
        assert "total_slide_area_km2" in stats
        assert "avg_slope_angle"      in stats
        assert stats["avg_slope_angle"] > 0.0, "avg_slope_angle must be > 0°"

    def test_cyclone_stats_keys(self, svc: MLService) -> None:
        """Cyclone stats must include max_wind_speed_kmh and storm_surge_max_m."""
        stats = svc.get_event_stats("odisha_2023", "cyclone")
        assert "max_wind_speed_kmh" in stats
        assert "storm_surge_max_m"  in stats
        assert stats["max_wind_speed_kmh"] > 0.0, "max_wind_speed_kmh must be > 0"
        assert stats["storm_surge_max_m"]  > 0.0, "storm_surge_max_m must be > 0"

    def test_earthquake_stats_keys(self, svc: MLService) -> None:
        """Earthquake stats must include total_damage_area_km2 and destroyed_pct."""
        stats = svc.get_event_stats("gujarat_2024", "earthquake")
        assert "total_damage_area_km2" in stats
        assert "destroyed_pct"         in stats
        assert 0.0 <= stats["destroyed_pct"] <= 100.0, (
            f"destroyed_pct={stats['destroyed_pct']} outside [0, 100]"
        )


# ---------------------------------------------------------------------------
# LIVE DETECTION TESTS (non-flood = controlled error, no 500)
# ---------------------------------------------------------------------------

class TestRunDetectionLive:
    """run_detection_live() — non-flood modules return controlled errors."""

    @pytest.mark.parametrize("disaster_type,event_id", [
        ("wildfire",   "uttarakhand_2024"),
        ("landslide",  "himachal_2023"),
        ("cyclone",    "odisha_2023"),
        ("earthquake", "gujarat_2024"),
    ])
    def test_live_non_flood_returns_task_id(
        self, svc: MLService, disaster_type: str, event_id: str
    ) -> None:
        """Non-flood live detection must return a non-empty task_id string."""
        task_id = svc.run_detection_live(
            event_id      = event_id,
            disaster_type = disaster_type,
            bbox          = [80.0, 28.0, 82.0, 30.0],
            date_range    = ("2024-04-01", "2024-05-01"),
        )
        assert isinstance(task_id, str) and len(task_id) > 0, (
            f"{disaster_type}: expected non-empty task_id, got {task_id!r}"
        )

    @pytest.mark.parametrize("disaster_type,event_id", [
        ("wildfire",   "uttarakhand_2024"),
        ("landslide",  "himachal_2023"),
        ("cyclone",    "odisha_2023"),
        ("earthquake", "gujarat_2024"),
    ])
    def test_live_non_flood_status_is_error_not_500(
        self, svc: MLService, disaster_type: str, event_id: str
    ) -> None:
        """Non-flood task status must be 'error' (controlled) — never raises."""
        task_id = svc.run_detection_live(
            event_id      = event_id,
            disaster_type = disaster_type,
            bbox          = [80.0, 28.0, 82.0, 30.0],
            date_range    = ("2024-04-01", "2024-05-01"),
        )
        # Status is set synchronously for non-flood — no sleep needed
        status = svc.get_task_status(task_id)
        assert status["status"] == "error", (
            f"{disaster_type}: expected status='error', got '{status['status']}'"
        )

    @pytest.mark.parametrize("disaster_type,event_id", [
        ("wildfire",   "uttarakhand_2024"),
        ("landslide",  "himachal_2023"),
        ("cyclone",    "odisha_2023"),
        ("earthquake", "gujarat_2024"),
    ])
    def test_live_non_flood_error_has_module_field(
        self, svc: MLService, disaster_type: str, event_id: str
    ) -> None:
        """Error dict must contain 'module' key identifying the failing module."""
        task_id = svc.run_detection_live(
            event_id      = event_id,
            disaster_type = disaster_type,
            bbox          = [80.0, 28.0, 82.0, 30.0],
            date_range    = ("2024-04-01", "2024-05-01"),
        )
        status = svc.get_task_status(task_id)
        error  = status.get("error") or {}
        assert "module" in error, (
            f"{disaster_type}: error dict missing 'module' key: {error}"
        )
        assert error["module"] == disaster_type, (
            f"Expected error.module='{disaster_type}', got '{error['module']}'"
        )

    @pytest.mark.parametrize("disaster_type,event_id", [
        ("wildfire",   "uttarakhand_2024"),
        ("landslide",  "himachal_2023"),
        ("cyclone",    "odisha_2023"),
        ("earthquake", "gujarat_2024"),
    ])
    def test_live_non_flood_message_mentions_phase2(
        self, svc: MLService, disaster_type: str, event_id: str
    ) -> None:
        """Status message must mention 'Phase 2' to guide developers."""
        task_id = svc.run_detection_live(
            event_id      = event_id,
            disaster_type = disaster_type,
            bbox          = [80.0, 28.0, 82.0, 30.0],
            date_range    = ("2024-04-01", "2024-05-01"),
        )
        status  = svc.get_task_status(task_id)
        message = status.get("message", "")
        assert "Phase 2" in message, (
            f"{disaster_type}: message does not mention 'Phase 2': {message!r}"
        )

    def test_unknown_type_raises_valueerror_not_500(self, svc: MLService) -> None:
        """Unknown disaster_type must raise ValueError immediately."""
        with pytest.raises(ValueError, match="Unknown disaster type"):
            svc.run_detection_live(
                event_id      = "test",
                disaster_type = "tsunami",
                bbox          = [80.0, 28.0, 82.0, 30.0],
                date_range    = ("2024-01-01", "2024-01-31"),
            )

    def test_unknown_task_id_raises_keyerror(self, svc: MLService) -> None:
        """get_task_status with unknown task_id must raise KeyError."""
        with pytest.raises(KeyError):
            svc.get_task_status("00000000-0000-0000-0000-000000000000")
