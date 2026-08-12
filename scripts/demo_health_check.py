"""
OrbitalMind — Pre-Demo Health Check
=====================================
Verifies every system dependency is up and demo data is intact before
presenting to judges.

Run this script from the OrbitalMind repo root:
    python scripts/demo_health_check.py

Exit codes
----------
  0 — All checks PASSED  → DEMO READY
  1 — One or more checks FAILED  → fix before demo

Checks performed
----------------
  1. Demo data    — All 5 GeoJSON files exist and have >= 3 features
  2. PyTorch/CUDA — RTX 3050 detected, VRAM reported
  3. PostgreSQL   — Reachable on localhost:5432 (psycopg2)
  4. Ollama LLM   — Responding on http://localhost:11434/api/tags
  5. FastAPI      — Responding on http://localhost:8000/health
  6. React Dev    — Responding on http://localhost:5173
"""

from __future__ import annotations

import io
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

# ── UTF-8 stdout (Windows cp1252 fix) ───────────────────────────────────────
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# ── Repo root ────────────────────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# ── ANSI colours (auto-disabled on non-ANSI terminals) ──────────────────────
_USE_ANSI = sys.stdout.isatty() if hasattr(sys.stdout, "isatty") else False

def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _USE_ANSI else text

GREEN  = lambda t: _c("92", t)
RED    = lambda t: _c("91", t)
YELLOW = lambda t: _c("93", t)
CYAN   = lambda t: _c("96", t)
BOLD   = lambda t: _c("1",  t)
DIM    = lambda t: _c("2",  t)


# ── Check result dataclass ───────────────────────────────────────────────────

@dataclass
class CheckResult:
    name:     str
    passed:   bool
    detail:   str                  # one-line detail shown on same line as PASS/FAIL
    fix_hint: Optional[str] = None # shown indented below on FAIL


# ── Individual check functions ───────────────────────────────────────────────

def check_demo_data() -> list[CheckResult]:
    """Verify all 5 GeoJSON demo datasets exist and contain >= 3 features."""
    manifest_path = _REPO_ROOT / "backend" / "demo_data" / "events_manifest.json"
    if not manifest_path.exists():
        return [CheckResult(
            name   = "Demo data (manifest)",
            passed = False,
            detail = "events_manifest.json NOT FOUND",
            fix_hint = "python scripts/generate_mock_data.py",
        )]

    with manifest_path.open(encoding="utf-8") as fh:
        manifest = json.load(fh)

    results: list[CheckResult] = []
    for event in manifest.get("events", []):
        event_id  = event["event_id"]
        dtype     = event["disaster_type"]
        rel_path  = event["geojson_path"]
        abs_path  = _REPO_ROOT / "backend" / "demo_data" / rel_path
        label     = f"Demo data  [{dtype}/{event_id}]"

        if not abs_path.exists():
            results.append(CheckResult(
                name     = label,
                passed   = False,
                detail   = f"File missing: {rel_path}",
                fix_hint = "python scripts/generate_mock_data.py --force",
            ))
            continue

        try:
            with abs_path.open(encoding="utf-8") as fh:
                data = json.load(fh)
            n = len(data.get("features", []))
            if n < 3:
                results.append(CheckResult(
                    name     = label,
                    passed   = False,
                    detail   = f"Only {n} feature(s) — need >= 3",
                    fix_hint = "python scripts/generate_mock_data.py --force",
                ))
            else:
                results.append(CheckResult(
                    name   = label,
                    passed = True,
                    detail = f"{n} features — OK",
                ))
        except json.JSONDecodeError as exc:
            results.append(CheckResult(
                name     = label,
                passed   = False,
                detail   = f"Invalid JSON: {exc}",
                fix_hint = "python scripts/generate_mock_data.py --force",
            ))

    return results


def check_pytorch_cuda() -> CheckResult:
    """Detect PyTorch and RTX 3050 GPU."""
    name = "PyTorch + CUDA (RTX 3050)"
    try:
        import torch
    except ImportError:
        return CheckResult(
            name     = name,
            passed   = False,
            detail   = "PyTorch not installed",
            fix_hint = "pip install torch torchvision --index-url https://download.pytorch.org/whl/cu118",
        )

    if not torch.cuda.is_available():
        return CheckResult(
            name     = name,
            passed   = False,
            detail   = f"CUDA not available  (PyTorch {torch.__version__})",
            fix_hint = (
                "1. Install CUDA 11.8 drivers\n"
                "         2. pip install torch --index-url https://download.pytorch.org/whl/cu118\n"
                "         3. Ensure RTX 3050 driver is up-to-date (nvidia-smi)"
            ),
        )

    device_name = torch.cuda.get_device_name(0)
    vram_mb     = torch.cuda.get_device_properties(0).total_memory // (1024 ** 2)
    version     = torch.__version__
    return CheckResult(
        name   = name,
        passed = True,
        detail = f"{device_name} — {vram_mb:,} MB VRAM  (PyTorch {version})",
    )


def check_postgresql() -> CheckResult:
    """Try to connect to PostgreSQL on localhost:5432."""
    name = "PostgreSQL (localhost:5432)"
    try:
        import psycopg2  # type: ignore[import]
    except ImportError:
        return CheckResult(
            name     = name,
            passed   = False,
            detail   = "psycopg2 not installed",
            fix_hint = "pip install psycopg2-binary",
        )

    try:
        conn = psycopg2.connect(
            host     = "localhost",
            port     = 5432,
            dbname   = "postgres",
            user     = "postgres",
            password = "postgres",
            connect_timeout = 3,
        )
        cur = conn.cursor()
        cur.execute("SELECT version();")
        version = cur.fetchone()[0].split(",")[0]   # e.g. "PostgreSQL 16.2"
        cur.close()
        conn.close()
        return CheckResult(
            name   = name,
            passed = True,
            detail = version,
        )
    except Exception as exc:
        short = str(exc).splitlines()[0][:80]
        return CheckResult(
            name     = name,
            passed   = False,
            detail   = f"Connection failed: {short}",
            fix_hint = (
                'Windows PowerShell:\n'
                '         pg_ctl start -D "C:\\Program Files\\PostgreSQL\\16\\data"\n'
                '         # or open Services → postgresql-x64-16 → Start'
            ),
        )


def check_ollama() -> CheckResult:
    """Ping Ollama on http://localhost:11434."""
    name = "Ollama LLM (localhost:11434)"
    try:
        import requests  # type: ignore[import]
    except ImportError:
        return CheckResult(
            name     = name,
            passed   = False,
            detail   = "requests not installed",
            fix_hint = "pip install requests",
        )

    try:
        t0   = time.perf_counter()
        resp = requests.get("http://localhost:11434/api/tags", timeout=3)
        ms   = int((time.perf_counter() - t0) * 1000)
        if resp.status_code == 200:
            data   = resp.json()
            models = [m["name"] for m in data.get("models", [])]
            model_str = ", ".join(models) if models else "no models loaded"
            return CheckResult(
                name   = name,
                passed = True,
                detail = f"Running  ({ms}ms)  models: {model_str}",
            )
        return CheckResult(
            name     = name,
            passed   = False,
            detail   = f"HTTP {resp.status_code}",
            fix_hint = "ollama serve",
        )
    except Exception as exc:
        short = str(exc).splitlines()[0][:60]
        return CheckResult(
            name     = name,
            passed   = False,
            detail   = f"Not reachable: {short}",
            fix_hint = (
                "In a separate terminal:\n"
                "         ollama serve\n"
                "         ollama pull llama3.2:3b   # first run only"
            ),
        )


def check_fastapi() -> CheckResult:
    """GET http://localhost:8000/health."""
    name = "FastAPI backend (localhost:8000)"
    try:
        import requests  # type: ignore[import]
    except ImportError:
        return CheckResult(
            name=name, passed=False, detail="requests not installed",
            fix_hint="pip install requests",
        )

    try:
        t0   = time.perf_counter()
        resp = requests.get("http://localhost:8000/health", timeout=3)
        ms   = int((time.perf_counter() - t0) * 1000)
        if resp.status_code == 200:
            body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            ver  = body.get("version", "")
            return CheckResult(
                name   = name,
                passed = True,
                detail = f"200 OK  ({ms}ms)" + (f"  v{ver}" if ver else ""),
            )
        return CheckResult(
            name     = name,
            passed   = False,
            detail   = f"HTTP {resp.status_code}  ({ms}ms)",
            fix_hint = "uvicorn backend.main:app --reload --port 8000",
        )
    except Exception as exc:
        short = str(exc).splitlines()[0][:60]
        return CheckResult(
            name     = name,
            passed   = False,
            detail   = f"Not reachable: {short}",
            fix_hint = (
                "In a separate terminal (from OrbitalMind/):\n"
                "         uvicorn backend.main:app --reload --port 8000"
            ),
        )


def check_react() -> CheckResult:
    """GET http://localhost:5173 (Vite dev server)."""
    name = "React dev server (localhost:5173)"
    try:
        import requests  # type: ignore[import]
    except ImportError:
        return CheckResult(
            name=name, passed=False, detail="requests not installed",
            fix_hint="pip install requests",
        )

    try:
        t0   = time.perf_counter()
        resp = requests.get("http://localhost:5173", timeout=3)
        ms   = int((time.perf_counter() - t0) * 1000)
        if resp.status_code in (200, 304):
            return CheckResult(
                name   = name,
                passed = True,
                detail = f"HTTP {resp.status_code}  ({ms}ms) — Vite running",
            )
        return CheckResult(
            name     = name,
            passed   = False,
            detail   = f"HTTP {resp.status_code}",
            fix_hint = "cd frontend && npm run dev",
        )
    except Exception as exc:
        short = str(exc).splitlines()[0][:60]
        return CheckResult(
            name     = name,
            passed   = False,
            detail   = f"Not reachable: {short}",
            fix_hint = (
                "In a separate terminal:\n"
                "         cd frontend\n"
                "         npm install   # first run only\n"
                "         npm run dev"
            ),
        )


# ── Printer ──────────────────────────────────────────────────────────────────

_NAME_WIDTH   = 42
_BADGE_PASS   = "  PASS  "
_BADGE_FAIL   = "  FAIL  "
_SEP          = "─" * 72


def _print_result(r: CheckResult) -> None:
    badge  = GREEN(f"[{_BADGE_PASS}]") if r.passed else RED(f"[{_BADGE_FAIL}]")
    name   = BOLD(r.name[:_NAME_WIDTH].ljust(_NAME_WIDTH))
    detail = DIM(r.detail) if r.passed else YELLOW(r.detail)
    print(f"  {badge}  {name}  {detail}")

    if not r.passed and r.fix_hint:
        for line in r.fix_hint.splitlines():
            print(f"             {DIM('FIX:')}  {line}")


# ── Orchestrator ─────────────────────────────────────────────────────────────

def run_all_checks() -> int:
    """Run every health check and print a formatted report.

    Returns
    -------
    int
        Number of failed checks (0 = all PASSED).
    """
    print()
    print(BOLD("=" * 72))
    print(BOLD("   OrbitalMind — Pre-Demo Health Check"))
    print(BOLD("=" * 72))
    print()

    all_results: list[CheckResult] = []

    # ── 1. Demo data ──────────────────────────────────────────────────────
    print(BOLD("  ● Demo Data"))
    print(f"  {_SEP}")
    demo_results = check_demo_data()
    for r in demo_results:
        _print_result(r)
        all_results.append(r)
    print()

    # ── 2. GPU ────────────────────────────────────────────────────────────
    print(BOLD("  ● Hardware / ML Runtime"))
    print(f"  {_SEP}")
    gpu = check_pytorch_cuda()
    _print_result(gpu)
    all_results.append(gpu)
    print()

    # ── 3. Services ───────────────────────────────────────────────────────
    print(BOLD("  ● External Services"))
    print(f"  {_SEP}")
    for check_fn in [check_postgresql, check_ollama, check_fastapi, check_react]:
        r = check_fn()
        _print_result(r)
        all_results.append(r)
    print()

    # ── Summary ───────────────────────────────────────────────────────────
    n_fail   = sum(1 for r in all_results if not r.passed)
    n_pass   = len(all_results) - n_fail
    n_total  = len(all_results)

    print(BOLD("=" * 72))
    if n_fail == 0:
        print(BOLD(GREEN(f"  ✅  DEMO READY   —   {n_pass}/{n_total} checks PASSED")))
    else:
        print(BOLD(RED(  f"  ❌  {n_fail} issue{'s' if n_fail > 1 else ''} found   —   {n_pass}/{n_total} checks passed")))
        print()
        print(DIM("  Fix the RED items above before presenting to judges."))
        print(DIM("  Data checks (top section) MUST all be green."))
        print(DIM("  Services can be started just before the demo begins."))
    print(BOLD("=" * 72))
    print()

    return n_fail


# ── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    n_failures = run_all_checks()
    sys.exit(0 if n_failures == 0 else 1)
