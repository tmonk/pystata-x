#!/usr/bin/env python3
"""Full benchmark suite for libstata_fast vs baseline."""

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


# ====================================================================
# 1. Cold-start init
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
            print(f"    Run {i+1}: FAIL")
            continue
        if i >= N_WARMUP:
            times.append(elapsed)
        label = "Warmup" if i < N_WARMUP else f"Run {i-N_WARMUP+1}"
        print(f"    {label}: {elapsed*1000:.1f} ms")
    return times

# ====================================================================
# 2. Single-command latency
# ====================================================================

EXEC_LAT = f"""\
import sys, time, statistics, json
sys.path.insert(0, "{REPO_SRC}")
from pystata_x import _stata_fast as sf
sf.init("{STATA_ROOT}", "{STATA_EDITION}", splash=False)
for _ in range(10): sf.execute("display 1+1")
N = 2000
t = []
for _ in range(N):
    t0 = time.perf_counter()
    sf.execute("display 1+1")
    t.append(time.perf_counter() - t0)
ts = [x*1_000_000 for x in t]
print(json.dumps({{
    "mean_us": statistics.mean(ts), "median_us": statistics.median(ts),
    "stdev_us": statistics.stdev(ts) if len(ts)>=2 else 0,
    "min_us": min(ts), "max_us": max(ts), "n": N, "ops": N/sum(t)
}}))
"""

# ====================================================================
# 3. Multi-line batch
# ====================================================================

BATCH_LAT = f"""\
import sys, time, statistics, json
sys.path.insert(0, "{REPO_SRC}")
from pystata_x import _stata_fast as sf
sf.init("{STATA_ROOT}", "{STATA_EDITION}", splash=False)
for _ in range(5):
    sf.execute("sysuse auto, clear\\\\nregress price mpg weight\\\\npredict pred\\\\nsummarize pred")
N = 100
t = []
for _ in range(N):
    t0 = time.perf_counter()
    sf.execute("sysuse auto, clear\\\\nregress price mpg weight\\\\npredict pred\\\\nsummarize pred")
    t.append(time.perf_counter() - t0)
ts = [x*1_000_000 for x in t]
print(json.dumps({{
    "mean_us": statistics.mean(ts), "median_us": statistics.median(ts),
    "n": N, "ops": N/sum(t)
}}))
"""

# ====================================================================
# 4. Output drain overhead (not applicable — execute always drains)
#    Measure the overhead of calling get_output after execute instead
# ====================================================================

OUTPUT_DRAIN = f"""\
import sys, time, statistics, json
sys.path.insert(0, "{REPO_SRC}")
from pystata_x import _stata_fast as sf
sf.init("{STATA_ROOT}", "{STATA_EDITION}", splash=False)
for _ in range(10): sf.execute("display 1+1")
N = 2000
t = []
for _ in range(N):
    sf.execute("display 1+1")  # drains output internally
    t0 = time.perf_counter()
    out = sf.get_output()
    t.append(time.perf_counter() - t0)
ts = [x*1_000_000 for x in t]
print(json.dumps({{
    "mean_us": statistics.mean(ts), "median_us": statistics.median(ts),
    "n": N
}}))
"""

# ====================================================================
# 5. Warm-execute (same process, no subprocess cost)
# ====================================================================

WARM_EXEC = f"""\
import sys, time, statistics, json
sys.path.insert(0, "{REPO_SRC}")
from pystata_x import _stata_fast as sf
sf.init("{STATA_ROOT}", "{STATA_EDITION}", splash=False)
# Not warmup — just test reused ctx
for _ in range(5): sf.execute("display 1+1")
print("OK", flush=True)
"""

# ====================================================================
# main
# ====================================================================

def main():
    print("=" * 70)
    print("  LIBSTATA_FAST — FULL BENCHMARK SUITE")
    print(f"  Branch: {_get_commit()}")
    print("=" * 70)
    print()

    results = {}

    # 1. Cold init
    print("[1/5] Cold-start init time")
    print(f"  ({N_WARMUP} warmup + {N_MEASURED} measured)")
    print()
    cold = measure_cold_init()
    if cold:
        results["cold_init_ms"] = {
            "min": min(cold) * 1000, "median": statistics.median(cold) * 1000,
            "mean": statistics.mean(cold) * 1000, "max": max(cold) * 1000,
            "n": len(cold),
        }

    # 2. Single-command latency
    print(f"\n[2/5] Command latency (2000x 'display 1+1')")
    lat = None
    elapsed, out, err = run_script(EXEC_LAT, timeout=120)
    for line in out.strip().splitlines():
        if line.startswith("{"):
            lat = json.loads(line)
            break
    if lat:
        results["exec_latency_us"] = lat
        print(f"    Mean:   {lat['mean_us']:.1f} µs")
        print(f"    Median: {lat['median_us']:.1f} µs")
        print(f"    Min:    {lat['min_us']:.1f} µs")
        print(f"    Max:    {lat['max_us']:.1f} µs")
        print(f"    Ops/s:  {lat['ops']:.0f}")

    # 3. Multi-line batch
    print(f"\n[3/5] Multi-line batch (100x regression)")
    batch = None
    elapsed, out, err = run_script(BATCH_LAT, timeout=120)
    for line in out.strip().splitlines():
        if line.startswith("{"):
            batch = json.loads(line)
            break
    if batch:
        results["batch_us"] = batch
        print(f"    Mean:   {batch['mean_us']:.0f} µs")
        print(f"    Median: {batch['median_us']:.0f} µs")
        print(f"    Ops/s:  {batch['ops']:.0f}")

    # 4. Output drain
    print(f"\n[4/5] Output drain overhead (2000x get_output after execute)")
    drain = None
    elapsed, out, err = run_script(OUTPUT_DRAIN, timeout=120)
    for line in out.strip().splitlines():
        if line.startswith("{"):
            drain = json.loads(line)
            break
    if drain:
        results["output_drain_us"] = drain
        print(f"    Mean:   {drain['mean_us']:.1f} µs")
        print(f"    Median: {drain['median_us']:.1f} µs")

    # 5. Comparison with baseline
    print(f"\n[5/5] Comparison vs baseline")
    try:
        bl = json.loads(Path(
            REPO_ROOT / "benchmarks" / "history" / "baseline_20260519_044834_70f55e3.json"
        ).read_text())
        bl_med = bl["exec_latency_us"]["median_us"]
        if lat:
            speedup = bl_med / lat["median_us"]
            print(f"    Baseline median:  {bl_med:.1f} µs")
            print(f"    stata_fast median: {lat['median_us']:.1f} µs")
            print(f"    Speedup:           {speedup:.1f}x")
            results["speedup_vs_baseline"] = speedup
        bl_batch = bl.get("batch_us", {}).get("median_us")
        if bl_batch and batch:
            print(f"    Batch baseline:    {bl_batch:.0f} µs")
            print(f"    Batch stata_fast:  {batch['median_us']:.0f} µs")
            print(f"    Batch speedup:     {bl_batch / batch['median_us']:.1f}x")
    except (FileNotFoundError, KeyError) as e:
        print(f"    (baseline not available: {e})")

    # Save results
    hist_dir = REPO_ROOT / "benchmarks" / "history"
    hist_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    commit = _get_commit()
    dest = hist_dir / f"stata_fast_full_{ts}_{commit}.json"
    results["meta"] = {
        "timestamp": ts, "commit": commit,
        "machine": _machine(), "python": sys.version,
        "stata_root": STATA_ROOT, "edition": STATA_EDITION,
    }
    with open(dest, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n  Results saved: {dest}")


if __name__ == "__main__":
    main()
