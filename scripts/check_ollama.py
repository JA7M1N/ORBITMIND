"""
OrbitalMind — Ollama Health Check
====================================
Checks if the local Ollama server is running and the required model is
available. Run this before the demo to confirm LLM narration will work.

Usage
-----
    python scripts/check_ollama.py
    python scripts/check_ollama.py --model llama3.2:3b --url http://localhost:11434
    python scripts/check_ollama.py --test-prompt   (sends a short test generation)

Exit codes
----------
    0  Ollama is up and model is available
    1  Ollama is up but model is missing
    2  Ollama is not reachable
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
import urllib.error


def banner(msg: str) -> None:
    width = 58
    print(f"\n{'=' * width}")
    print(f"  {msg}")
    print(f"{'=' * width}")


def ok(msg: str)   -> None: print(f"  [  OK  ]  {msg}")
def warn(msg: str) -> None: print(f"  [ WARN ]  {msg}")
def fail(msg: str) -> None: print(f"  [ FAIL ]  {msg}")
def info(msg: str) -> None: print(f"  [ INFO ]  {msg}")


def get_json(url: str, timeout: int = 4) -> dict | None:
    """Fetch JSON from a URL; return None on any error."""
    try:
        req  = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def post_json(url: str, data: dict, timeout: int = 30) -> dict | None:
    """POST JSON to a URL; return None on any error."""
    try:
        body = json.dumps(data).encode("utf-8")
        req  = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception as exc:
        return None


def run(args: argparse.Namespace) -> int:
    banner("OrbitalMind — Ollama LLM Health Check")
    print(f"\n  URL   : {args.url}")
    print(f"  Model : {args.model}")

    # ── 1. Ping Ollama ─────────────────────────────────────────────────────
    banner("STEP 1 — Ping Ollama server")
    tags_url = f"{args.url}/api/tags"
    data = get_json(tags_url)

    if data is None:
        fail(f"Cannot reach Ollama at {args.url}")
        print()
        print("  Possible fixes:")
        print("    1. Install Ollama: https://ollama.com/download")
        print("    2. Start Ollama:   ollama serve")
        print("    3. Check port:     netstat -an | findstr 11434")
        return 2

    ok(f"Ollama is running at {args.url}")

    # ── 2. List available models ───────────────────────────────────────────
    banner("STEP 2 — Check available models")
    models = data.get("models", [])
    if models:
        info(f"Found {len(models)} model(s):")
        for m in models:
            size_gb = m.get("size", 0) / 1e9
            print(f"    • {m['name']:<30}  {size_gb:.1f} GB")
    else:
        warn("No models pulled yet.")
        print(f"\n  Pull the required model:")
        print(f"    ollama pull {args.model}")
        print(f"    (approx. 2.0 GB download for llama3.2:3b)")
        return 1

    # ── 3. Check for required model ────────────────────────────────────────
    banner(f"STEP 3 — Check for {args.model}")
    model_names = [m["name"] for m in models]
    model_base  = args.model.split(":")[0]

    exact_match = args.model in model_names
    base_match  = any(n.startswith(model_base) for n in model_names)

    if exact_match:
        ok(f"'{args.model}' is available — exact match")
    elif base_match:
        matched = [n for n in model_names if n.startswith(model_base)]
        warn(f"'{args.model}' not found, but found: {matched}")
        info("OrbitalMind will use the first matching variant automatically.")
    else:
        fail(f"Model '{args.model}' is NOT available")
        print()
        print(f"  Fix: ollama pull {args.model}")
        print(f"  This downloads approx. 2.0 GB (llama3.2:3b quantised Q4_K_M)")
        print()
        print(f"  Alternative lighter models (< 1 GB):")
        print(f"    ollama pull qwen2.5:0.5b   (0.4 GB — fastest, lower quality)")
        print(f"    ollama pull phi3:mini       (0.8 GB — good quality)")
        return 1

    # ── 4. Test generation (optional) ──────────────────────────────────────
    if args.test_prompt:
        banner("STEP 4 — Test generation")
        test_prompt = (
            "You are an emergency response AI. Write exactly 2 sentences "
            "about flood response in Kerala. Facts only, no emojis."
        )
        info(f"Sending test prompt to {args.model}...")
        info(f"Prompt: \"{test_prompt[:60]}...\"")

        t0 = time.perf_counter()
        result = post_json(
            f"{args.url}/api/chat",
            {
                "model":  args.model,
                "stream": False,
                "options": {"temperature": 0.3, "num_predict": 80},
                "messages": [{"role": "user", "content": test_prompt}],
            },
            timeout=30,
        )
        elapsed = time.perf_counter() - t0

        if result and result.get("message"):
            text = result["message"]["content"]
            ok(f"Response received in {elapsed:.1f}s")
            print()
            print("  Generated text:")
            for line in text.strip().split("\n"):
                print(f"    {line}")
            print()
            # Estimate demo performance
            if elapsed < 5:
                info("Performance: EXCELLENT — narrations will appear in < 5 s")
            elif elapsed < 10:
                info("Performance: GOOD — narrations will appear in < 10 s")
            elif elapsed < 15:
                warn("Performance: SLOW — narrations will appear in 10–15 s")
                warn("Consider using --model phi3:mini for faster responses.")
            else:
                warn(f"Performance: VERY SLOW ({elapsed:.0f}s) — fallback narrations")
                warn("will be used when generation exceeds 12 s timeout.")
        else:
            fail("Generation failed — model may be loading (try again in 30 s)")
            return 1

    # ── Summary ────────────────────────────────────────────────────────────
    banner("Summary")
    ok("Ollama is running")
    if exact_match or base_match:
        ok(f"Model '{args.model}' (or variant) available")
    if args.test_prompt:
        ok("Test generation successful")

    print()
    print("  OrbitalMind narration endpoint is READY.")
    print("  GET /api/narration/kerala-2018/ernakulam")
    print("  POST /api/report/kerala-2018")
    print()

    return 0


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    p = argparse.ArgumentParser(description="OrbitalMind Ollama health check")
    p.add_argument("--url",         default="http://localhost:11434",
                   help="Ollama server base URL")
    p.add_argument("--model",       default="llama3.2:3b",
                   help="Expected model tag")
    p.add_argument("--test-prompt", action="store_true",
                   help="Send a short generation test and measure response time")
    sys.exit(run(p.parse_args()))
