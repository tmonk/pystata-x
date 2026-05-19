#!/usr/bin/env python3
"""Benchmark libstata_fast against the baseline.

Measures:
  1. Cold-start init time (libstata_fast)
  2. Command execution latency (libstata_fast)
  3. Comparison vs baseline
"""

from __future__ import annotations

import json
import statistics
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
REPO_SRC = str(REPO_ROOT / "src")
PYTHON = sys.executable
STATA_ROOT = "/Applications/StataNow"
STATA_EDITION = "se"

_ENV = {**__import__("os").environ, "PYTHONUNBUFFERED": "1"}

N_WARMUP = 3
N_MEASURED = 10

# ====================================================================
# Helper
# ====================================================================

def run_script(script: str, timeout: int = 60) -> tuple[float, str, str]:
    t0 = time.perf_counter()
    r = subprocess.run([PYTHON, "-c", script], capture_output=True, text=True,
                       timeout=timeout, env=_ENV)
    return time.perf_counter() - t0, r.stdout, r.stderr

# ====================================================================
# 1. Cold-start init time
# ====================================================================

COLD_INIT = f"""\
import sys
sys.path.insert(0, "{REPO_SRC}")
from pystata_x import _stata_fast as sf
sf.init("{STATA_ROOT}", "{STATA_EDITION}", splash=False)
print("OK", flush=True)
"""

def measure_cold_init() -> list[float]:
    times = []
    for i in range(N_WARMUP + N_MEASURED):
        elapsed, out, err = run_script(COLD_INIT, timeout=60)
        if "OK" not in out:
            print(f"    Run {i+1}: FAIL — {err.strip()[:120] or out.strip()[:120]}")
            continue
        if i >= N_WARMUP:
            times.append(elapsed)
        label = "Warmup" if i < N_WARMUP else f"Run {i-N_WARMUP+1}"
        print(f"    {label} {i+1}: {elapsed*1000:.1f} ms")
    return times

# ====================================================================
# 2. Command execution latency
# ====================================================================

EXEC_BENCH = f"""\
import sys, time, statistics, json
sys.path.insert(0, "{REPO_SRC}")
from pystata_x import _stata_fast as sf

sf.init("{STATA_ROOT}", "{STATA_EDITION}", splash=False)

# Warmup
for _ in range(10):
    sf.execute("display 1+1")

# Slow path: multi-call via execute + get_output (simulating _core)
N = 1000
t = []
for _ in range(N):
    t0 = time.perf_counter()
    out, rc = sf.execute("display 1+1")
    t.append(time.perf_counter() - t0)

ts = [x * 1_000_000 for x in t]
print(json.dumps({{
    "mean_us": statistics.mean(ts),
    "median_us": statistics.median(ts),
    "stdev_us": statistics.stdev(ts) if len(ts) >= 2 else 0,
    "min_us": min(ts),
    "max_us": max(ts),
    "n": N,
    "ops": N / sum(t),
}}))
"""

def measure_latency() -> dict | None:
    elapsed, out, err = run_script(EXEC_BENCH, timeout=120)
    for line in out.strip().splitlines():
        if line.startswith("{"):
            return json.loads(line)
    print(f"    FAILED — {err.strip()[:200] or out.strip()[:200]}")
    return None

# ====================================================================
# main
# ====================================================================

def main():
    print("=" * 70)
    print("  LIBSTATA_FAST BENCHMARK")
    print("=" * 70)
    print()

    results = {}

    # 1. Cold init
    print("[1/2] Cold-start init time")
    print(f"  ({N_WARMUP} warmup + {N_MEASURED} measured, each in fresh subprocess)")
    print()
    cold = measure_cold_init()
    if cold:
        results["cold_init_ms"] = {
            "min": min(cold) * 1000,
            "median": statistics.median(cold) * 1000,
            "mean": statistics.mean(cold) * 1000,
            "max": max(cold) * 1000,
            "n": len(cold),
        }
        if len(cold) >= 2:
            results["cold_init_ms"]["stdev"] = statistics.stdev(cold) * 1000

    # 2. Latency
    print(f"\n[2/2] Command execution latency (1000x 'display 1+1')")
    print()
    lat = measure_latency()
    if lat:
        results["exec_latency_us"] = lat
        print(f"    Mean:   {lat['mean_us']:.1f} µs")
        print(f"    Median: {lat['median_us']:.1f} µs")
        print(f"    Min:    {lat['min_us']:.1f} µs")
        print(f"    Max:    {lat['max_us']:.1f} µs")
        print(f"    Ops/s:  {lat['ops']:.0f}")

    # Compare with baseline
    try:
        bl = json.loads(Path(REPO_ROOT / "benchmarks" / "history" / "baseline_20260519_044834_70f55e3.json").read_text())
        base_median = bl["exec_latency_us"]["median_us"]
        if lat:
            speedup = base_median / lat["median_us"]
            print(f"\n  Speedup vs baseline: {speedup:.1f}x")
            print(f"    Baseline median:  {base_median:.1f} µs")
            print(f"    stata_fast median: {lat['median_us']:.1f} µs")
            results["speedup_vs_baseline"] = speedup
    except (FileNotFoundError, KeyError):
        print("\n  (baseline not available for comparison)")

    # Save
    hist_dir = REPO_ROOT / "benchmarks" / "history"
    hist_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    commit = _get_commit()
    dest = hist_dir / f"stata_fast_{ts}_{commit}.json"
    results["meta"] = {
        "timestamp": ts,
        "commit": commit,
        "machine": _machine(),
        "python": sys.version,
        "stata_root": STATA_ROOT,
    }
    with open(dest, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n  Results saved: {dest}")


def _get_commit() -> str:
    try:
        r = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                           capture_output=True, text=True, timeout=5, cwd=REPO_ROOT)
        return r.stdout.strip() if r.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def _machine():
    import platform
    return f"{platform.machine()} ({platform.system()} {platform.release()})"


if __name__ == "__main__":
    main()
