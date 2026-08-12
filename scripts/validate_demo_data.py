from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from typing import Any

# Force UTF-8 output on Windows (avoids cp1252 emoji/box-char errors)
if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

"""
OrbitalMind — Demo Data Validator
===================================
Reads events_manifest.json and validates every GeoJSON demo dataset.

Checks performed per event
--------------------------
  1. GeoJSON file exists on disk
  2. File is valid JSON (no parse errors)
  3. Root object is a GeoJSON FeatureCollection
  4. Has >= 3 features
  5. Every feature has a ``confidence`` property (float 0–1)
  6. All geometries are valid (Shapely ``is_valid`` / ``is_simple``)

Exit codes
----------
  0 — all events PASS
  1 — one or more events FAIL

Usage
-----
    python scripts/validate_demo_data.py

    # Non-zero exit on failure (useful in CI):
    python scripts/validate_demo_data.py && echo "All good"
"""

# ---------------------------------------------------------------------------
# Repo root
# ---------------------------------------------------------------------------
_REPO_ROOT     = Path(__file__).resolve().parents[1]
_DEMO_BASE     = _REPO_ROOT / "backend" / "demo_data"
_MANIFEST_PATH = _DEMO_BASE / "events_manifest.json"

# Minimum number of GeoJSON features per event
MIN_FEATURES = 3


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def check_file_exists(path: Path) -> tuple[bool, str]:
    """Check that the GeoJSON file exists on disk."""
    if path.exists():
        return True, "file exists"
    return False, f"FILE NOT FOUND: {path}"


def check_valid_json(path: Path) -> tuple[bool, str, Any]:
    """Parse the file as JSON and return (ok, message, data)."""
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return True, "valid JSON", data
    except json.JSONDecodeError as exc:
        return False, f"JSON PARSE ERROR: {exc}", None
    except Exception as exc:
        return False, f"READ ERROR: {exc}", None


def check_feature_collection(data: Any) -> tuple[bool, str]:
    """Verify the root object is a GeoJSON FeatureCollection."""
    if not isinstance(data, dict):
        return False, "root is not a JSON object"
    if data.get("type") != "FeatureCollection":
        return False, f"type is '{data.get('type')}', expected 'FeatureCollection'"
    if "features" not in data:
        return False, "missing 'features' key"
    return True, "FeatureCollection"


def check_feature_count(data: dict, min_count: int = MIN_FEATURES) -> tuple[bool, str]:
    """Check that the FeatureCollection has at least ``min_count`` features."""
    n = len(data.get("features", []))
    if n >= min_count:
        return True, f"{n} features"
    return False, f"only {n} feature(s) — need >= {min_count}"


def check_confidence_property(data: dict) -> tuple[bool, str]:
    """Verify every feature has a ``confidence`` property with a numeric value."""
    features = data.get("features", [])
    if not features:
        return False, "no features to check"

    missing = []
    invalid = []

    for i, feat in enumerate(features):
        props = feat.get("properties") or {}
        if "confidence" not in props:
            missing.append(i)
            continue
        conf = props["confidence"]
        if not isinstance(conf, (int, float)):
            invalid.append((i, conf))
            continue
        if not (0.0 <= conf <= 1.0):
            invalid.append((i, conf))

    issues = []
    if missing:
        issues.append(f"missing in feature(s) {missing}")
    if invalid:
        issues.append(f"invalid value in feature(s) {invalid}")

    if issues:
        return False, "confidence errors: " + "; ".join(issues)
    return True, "all features have confidence ∈ [0,1]"


def check_geometry_validity(data: dict) -> tuple[bool, str]:
    """Check all geometries for self-intersections using Shapely.

    - Polygon / MultiPolygon: ``shapely.geometry.shape(g).is_valid``
    - LineString / MultiLineString: ``shapely.geometry.shape(g).is_simple``
    - Point / MultiPoint: always valid

    Returns (False, details) on the first invalid geometry found.
    """
    try:
        from shapely.geometry import shape as shapely_shape
    except ImportError:
        return False, "shapely not installed — run: pip install shapely"

    features = data.get("features", [])
    errors   = []

    for i, feat in enumerate(features):
        geom_dict = feat.get("geometry")
        if geom_dict is None:
            errors.append(f"feature {i}: null geometry")
            continue

        geom_type = geom_dict.get("type", "")

        try:
            geom = shapely_shape(geom_dict)
        except Exception as exc:
            errors.append(f"feature {i}: could not parse geometry — {exc}")
            continue

        if geom_type in ("Polygon", "MultiPolygon"):
            if not geom.is_valid:
                # Get explanation
                from shapely.validation import explain_validity
                reason = explain_validity(geom)
                errors.append(f"feature {i} (Polygon): invalid — {reason}")

        elif geom_type in ("LineString", "MultiLineString"):
            if not geom.is_simple:
                errors.append(f"feature {i} (LineString): self-intersection detected")

        elif geom_type in ("Point", "MultiPoint"):
            pass   # Points are always valid

        else:
            errors.append(f"feature {i}: unknown geometry type '{geom_type}'")

    if errors:
        return False, "; ".join(errors)
    return True, f"all {len(features)} geometries valid"


# ---------------------------------------------------------------------------
# Per-event validation orchestrator
# ---------------------------------------------------------------------------

def validate_event(event: dict) -> dict:
    """Run all validation checks for a single event.

    Parameters
    ----------
    event : dict
        A single entry from ``events_manifest.json["events"]``.

    Returns
    -------
    dict
        Validation result with keys:
        ``event_id``, ``display_name``, ``geojson_path``,
        ``passed``, ``feature_count``, ``checks`` (list of check results).
    """
    event_id     = event["event_id"]
    display_name = event["display_name"]
    rel_path     = event["geojson_path"]
    abs_path     = _DEMO_BASE / rel_path

    result = {
        "event_id":      event_id,
        "display_name":  display_name,
        "geojson_path":  rel_path,
        "abs_path":      str(abs_path),
        "feature_count": 0,
        "passed":        False,
        "checks":        [],
    }

    def add_check(name: str, ok: bool, msg: str) -> bool:
        result["checks"].append({"check": name, "ok": ok, "message": msg})
        return ok

    # 1. File exists
    ok, msg = check_file_exists(abs_path)
    if not add_check("file_exists", ok, msg):
        return result  # can't proceed without the file

    # 2. Valid JSON
    ok, msg, data = check_valid_json(abs_path)
    if not add_check("valid_json", ok, msg):
        return result  # can't proceed without parsed data

    # 3. FeatureCollection
    ok, msg = check_feature_collection(data)
    if not add_check("feature_collection", ok, msg):
        return result

    # 4. Feature count
    ok, msg = check_feature_count(data)
    add_check("min_features", ok, msg)
    result["feature_count"] = len(data.get("features", []))

    # 5. Confidence property
    ok, msg = check_confidence_property(data)
    add_check("confidence_property", ok, msg)

    # 6. Geometry validity
    ok, msg = check_geometry_validity(data)
    add_check("geometry_valid", ok, msg)

    # Overall pass: all checks must be OK
    result["passed"] = all(c["ok"] for c in result["checks"])
    return result


# ---------------------------------------------------------------------------
# Report printer
# ---------------------------------------------------------------------------

def _status_icon(ok: bool) -> str:
    return "PASS" if ok else "FAIL"


def print_summary_table(results: list[dict]) -> None:
    """Print a formatted validation table to stdout."""
    col_event    = 38
    col_status   = 6
    col_features = 10
    col_checks   = 6

    sep = "-" * (col_event + col_status + col_features + col_checks + 9)

    print("\n" + "=" * len(sep))
    print("  OrbitalMind — Demo Data Validation Report")
    print("=" * len(sep))

    header = (
        f"  {'Event':<{col_event}} "
        f"{'Status':<{col_status}} "
        f"{'Features':<{col_features}} "
        f"{'Checks'}"
    )
    print(header)
    print("  " + sep)

    all_passed = True
    for r in results:
        status      = _status_icon(r["passed"])
        n_feat      = r["feature_count"]
        n_checks    = len(r["checks"])
        n_pass      = sum(1 for c in r["checks"] if c["ok"])
        checks_str  = f"{n_pass}/{n_checks}"
        display     = r["display_name"][:col_event]

        row = (
            f"  {display:<{col_event}} "
            f"{status:<{col_status}} "
            f"{n_feat:<{col_features}} "
            f"{checks_str}"
        )
        print(row)

        # Print individual failed checks indented
        for chk in r["checks"]:
            if not chk["ok"]:
                print(f"         !! [{chk['check']}] FAIL: {chk['message']}")
                all_passed = False

    print("  " + sep)

    n_pass_total = sum(1 for r in results if r["passed"])
    overall      = "ALL PASS" if all_passed else f"{n_pass_total}/{len(results)} events passed"
    print(f"\n  Overall result: {overall}")
    print("=" * len(sep) + "\n")

    return all_passed  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Check list per check name (detail view)
# ---------------------------------------------------------------------------

def print_check_detail(results: list[dict]) -> None:
    """Print per-check detail for debugging failed events."""
    any_fail = any(not r["passed"] for r in results)
    if not any_fail:
        return

    print("─── Check Detail (failed events only) ───\n")
    for r in results:
        if r["passed"]:
            continue
        print(f"  Event: {r['event_id']}  →  {r['abs_path']}")
        for chk in r["checks"]:
            icon = "✓" if chk["ok"] else "✗"
            print(f"    [{icon}] {chk['check']:25}  {chk['message']}")
        print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    """Run validation for all events in events_manifest.json.

    Returns
    -------
    int
        Exit code: 0 = all PASS, 1 = any FAIL.
    """
    if not _MANIFEST_PATH.exists():
        print(f"[ERROR] Manifest not found: {_MANIFEST_PATH}")
        print("        Run: python scripts/generate_mock_data.py first")
        return 1

    with _MANIFEST_PATH.open("r", encoding="utf-8") as fh:
        manifest = json.load(fh)

    events  = manifest.get("events", [])
    if not events:
        print("[ERROR] events_manifest.json has no events.")
        return 1

    print(f"\n[INFO] Validating {len(events)} event(s) from manifest …")

    results = []
    for event in events:
        res = validate_event(event)
        results.append(res)

    all_passed = print_summary_table(results)
    print_check_detail(results)

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
