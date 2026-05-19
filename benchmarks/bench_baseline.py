#!/usr/bin/env python3
"""Baseline benchmark for pystata-x (current in-process libstata approach).

Measures:
  1. Cold-start initialisation time
  2. Command execution latency (single-line, simple)
  3. Command execution throughput (batched)
  4. Multi-line do-file execution

These numbers form the "before" baseline for the stata-fast IPC rewrite.
"""

# SPDX-FileCopyrightText: 2025 Thomas Monk <t.d.monk@lse.ac.uk>
# SPDX-License-Identifier: AGPL-3.0-only

from __future__ import annotations

import json
import os
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

_ENV = os.environ.copy()
_ENV["PYTHONUNBUFFERED"] = "1"

N_WARMUP = 3
N_MEASURED = 10

# ====================================================================
# Helper: run a Python script in a subprocess and measure wall time
# ====================================================================

def run_script(script: str, timeout: int = 60) -> tuple[float, str, str]:
    """Run *script* and return (elapsed_seconds, stdout, stderr)."""
    t0 = time.perf_counter()
    result = subprocess.run(
        [PYTHON, "-c", script],
        capture_output=True, text=True, timeout=timeout,
        env=_ENV,
    )
    elapsed = time.perf_counter() - t0
    return elapsed, result.stdout, result.stderr

# ====================================================================
# 1. Cold-start init time
# ====================================================================

COLD_INIT_SCRIPT = f"""\
import sys
sys.path.insert(0, "{REPO_SRC}")
from pystata_x import _config as _cfg
_cfg.init("{STATA_EDITION}", st_path="{STATA_ROOT}", splash=False)
print("OK", flush=True)
"""

def measure_cold_init() -> list[float]:
    """Return list of cold-start wall-clock times."""
    times: list[float] = []
    for i in range(N_WARMUP + N_MEASURED):
        elapsed, out, err = run_script(COLD_INIT_SCRIPT, timeout=60)
        if "OK" not in out:
            print(f"    Run {i+1}: FAILED — {err.strip()[:120] or out.strip()[:120]}")
            continue
        if i >= N_WARMUP:
            times.append(elapsed)
        label = "Warmup" if i < N_WARMUP else f"Run {i-N_WARMUP+1}"
        status = "OK" if elapsed > 0 else "FAIL"
        print(f"    {label} {i+1}: {elapsed*1000:.1f} ms  [{status}]")
    return times

# ====================================================================
# 2. Command execution latency (in-process, warm Stata)
# ====================================================================

EXEC_BENCH_SCRIPT = f"""\
import sys, time, statistics
sys.path.insert(0, "{REPO_SRC}")
from pystata_x import _config as _cfg
from pystata_x._core import execute

_cfg.init("{STATA_EDITION}", st_path="{STATA_ROOT}", splash=False)

# Warmup
for _ in range(10):
    execute("display 1+1", quietly=True)

# Measured loop
times = []
CMD = "display 1+1"
N = 2000
for _ in range(N):
    t0 = time.perf_counter()
    execute(CMD, quietly=True)
    times.append(time.perf_counter() - t0)

# Compute stats
times_ms = [t * 1000 for t in times]
mn = statistics.mean(times_ms)
md = statistics.median(times_ms)
sd = statistics.stdev(times_ms) if len(times_ms) >= 2 else 0
mi = min(times_ms)
ma = max(times_ms)
ops = N / sum(times)

# Output as JSON
import json
print(json.dumps({{
    "mean_us": mn * 1000,
    "median_us": md * 1000,
    "stdev_us": sd * 1000,
    "min_us": mi * 1000,
    "max_us": ma * 1000,
    "n": N,
    "ops": ops,
}}))
"""

def measure_exec_latency() -> dict | None:
    elapsed, out, err = run_script(EXEC_BENCH_SCRIPT, timeout=120)
    for line in out.strip().splitlines():
        if line.startswith("{"):
            return json.loads(line)
    print(f"    FAILED — {err.strip()[:200] or out.strip()[:200]}")
    return None

# ====================================================================
# 3. Throughput: batched execution (multi-statement do-file)
# ====================================================================

BATCH_SCRIPT = f"""\
import sys, time, statistics
sys.path.insert(0, "{REPO_SRC}")
from pystata_x import _config as _cfg
from pystata_x._core import execute

_cfg.init("{STATA_EDITION}", st_path="{STATA_ROOT}", splash=False)

# Warmup
for _ in range(5):
    execute("sysuse auto, clear\\nregress price mpg weight\\npredict pred\\nsummarize pred", quietly=True)

# Measured loop
times = []
N = 100
CODE = "sysuse auto, clear\\nregress price mpg weight\\npredict pred\\nsummarize pred"
for _ in range(N):
    t0 = time.perf_counter()
    execute(CODE, quietly=True)
    times.append(time.perf_counter() - t0)

times_ms = [t * 1000 for t in times]
import json
print(json.dumps({{
    "mean_us": statistics.mean(times_ms) * 1000,
    "median_us": statistics.median(times_ms) * 1000,
    "n": N,
    "ops": N / sum(times),
}}))
"""

def measure_batch() -> dict | None:
    elapsed, out, err = run_script(BATCH_SCRIPT, timeout=120)
    for line in out.strip().splitlines():
        if line.startswith("{"):
            return json.loads(line)
    print(f"    FAILED — {err.strip()[:200] or out.strip()[:200]}")
    return None

# ====================================================================
# 4. Output buffer drain overhead
# ====================================================================

OUTPUT_SCRIPT = f"""\
import sys, time, statistics
sys.path.insert(0, "{REPO_SRC}")
from pystata_x import _config as _cfg
from pystata_x._core import execute, get_output

_cfg.init("{STATA_EDITION}", st_path="{STATA_ROOT}", splash=False)

# Warmup
for _ in range(5):
    execute("display 1+1", quietly=True)
    _ = get_output()

# Measured loop
times = []
N = 2000
for _ in range(N):
    execute("display 1+1", quietly=True)
    t0 = time.perf_counter()
    out = get_output()
    times.append(time.perf_counter() - t0)

times_ms = [t * 1000 for t in times]
import json
print(json.dumps({{
    "mean_us": statistics.mean(times_ms) * 1000,
    "median_us": statistics.median(times_ms) * 1000,
    "n": N,
}}))
"""

def measure_output() -> dict | None:
    elapsed, out, err = run_script(OUTPUT_SCRIPT, timeout=120)
    for line in out.strip().splitlines():
        if line.startswith("{"):
            return json.loads(line)
    print(f"    FAILED — {err.strip()[:200] or out.strip()[:200]}")
    return None

# ====================================================================
# 5. Clean shutdown benchmark
# ====================================================================

SHUTDOWN_SCRIPT = f"""\
import sys
sys.path.insert(0, "{REPO_SRC}")
from pystata_x import _config as _cfg
_cfg.init("{STATA_EDITION}", st_path="{STATA_ROOT}", splash=False)
"""

def measure_shutdown() -> float | None:
    """Time a single init+shutdown cycle."""
    elapsed, out, err = run_script(SHUTDOWN_SCRIPT, timeout=60)
    return elapsed

# ====================================================================
# main
# ====================================================================

def _fmt_us(s: float) -> str:
    return f"{s*1_000_000:.1f}"

def main():
    print("=" * 70)
    print("  BASELINE BENCHMARK — pystata-x (in-process libstata)")
    print(f"  Branch: {_get_commit()}")
    print("=" * 70)
    print()

    results = {}

    # 1. Cold init
    print("[1/4] Cold-start initialisation time")
    print(f"  ({N_WARMUP} warmup + {N_MEASURED} measured)")
    print()
    cold_times = measure_cold_init()
    if cold_times:
        results["cold_init_ms"] = {
            "min": min(cold_times) * 1000,
            "median": statistics.median(cold_times) * 1000,
            "mean": statistics.mean(cold_times) * 1000,
            "max": max(cold_times) * 1000,
            "n": len(cold_times),
        }
        if len(cold_times) >= 2:
            results["cold_init_ms"]["stdev"] = statistics.stdev(cold_times) * 1000

    # 2. Execution latency
    print(f"\n[2/4] Command execution latency (2000x 'display 1+1')")
    exec_data = measure_exec_latency()
    if exec_data:
        results["exec_latency_us"] = exec_data
        print(f"    Mean:   {exec_data['mean_us']:.1f} µs")
        print(f"    Median: {exec_data['median_us']:.1f} µs")
        print(f"    Min:    {exec_data['min_us']:.1f} µs")
        print(f"    Max:    {exec_data['max_us']:.1f} µs")
        print(f"    Ops/s:  {exec_data['ops']:.0f}")

    # 3. Batch execution
    print(f"\n[3/4] Multi-line do-file execution (100x regression)")  
    batch_data = measure_batch()
    if batch_data:
        results["batch_us"] = batch_data
        print(f"    Mean:   {batch_data['mean_us']:.1f} µs")
        print(f"    Median: {batch_data['median_us']:.1f} µs")
        print(f"    Ops/s:  {batch_data['ops']:.0f}")

    # 4. Output drain
    print(f"\n[4/4] Output buffer drain overhead")
    out_data = measure_output()
    if out_data:
        results["output_drain_us"] = out_data
        print(f"    Mean:   {out_data['mean_us']:.1f} µs")
        print(f"    Median: {out_data['median_us']:.1f} µs")

    # Save results
    hist_dir = REPO_ROOT / "benchmarks" / "history"
    hist_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    commit = _get_commit()
    dest = hist_dir / f"baseline_{timestamp}_{commit}.json"
    results["meta"] = {
        "timestamp": timestamp,
        "commit": commit,
        "machine": _machine(),
        "python": sys.version,
        "stata_root": STATA_ROOT,
        "edition": STATA_EDITION,
    }
    with open(dest, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n  Results saved: {dest}")


def _get_commit() -> str:
    try:
        r = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                           capture_output=True, text=True, timeout=5,
                           cwd=REPO_ROOT)
        return r.stdout.strip() if r.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def _machine() -> str:
    import platform
    return f"{platform.machine()} ({platform.system()} {platform.release()})"


if __name__ == "__main__":
    main()
