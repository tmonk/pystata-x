#!/usr/bin/env python3
"""Benchmark fork-based cold init vs standard StataSO_Main init.

Demonstrates that forking from a pre-initialized master gives
~100x faster "cold" start (1.2 ms vs 130 ms).
"""

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
_ENV = {**__import__("os").environ, "PYTHONUNBUFFERED": "1"}

N_WARMUP = 3
N_MEASURED = 10


def run_script(script: str, timeout: int = 60) -> tuple[float, str, str]:
    t0 = time.perf_counter()
    r = subprocess.run([PYTHON, "-c", script], capture_output=True, text=True,
                       timeout=timeout, env=_ENV)
    return time.perf_counter() - t0, r.stdout, r.stderr


# ====================================================================
# 1. Standard cold init (StataSO_Main in fresh subprocess)
# ====================================================================

STD_INIT = f"""\
import sys
sys.path.insert(0, "{REPO_SRC}")
from pystata_x import _stata_fast as sf
sf.init("{STATA_ROOT}", "{STATA_EDITION}", splash=False)
print("OK", flush=True)
"""

# ====================================================================
# 2. Fork-based cold init
# ====================================================================

FORK_INIT = f"""\
import sys, os, time, statistics
sys.path.insert(0, "{REPO_SRC}")
from pystata_x import _stata_fast as sf

# Master init (one-time cost)
sf.init("{STATA_ROOT}", "{STATA_EDITION}", splash=False)

N = 100
t = []
for _ in range(N):
    t0 = time.perf_counter()
    pid = os.fork()
    if pid == 0:
        sf.execute("display 1+1")
        os._exit(0)
    else:
        os.waitpid(pid, 0)
        t.append(time.perf_counter() - t0)

ts = [x*1000 for x in t]
import json; print(json.dumps({{
    "mean_ms": statistics.mean(ts),
    "median_ms": statistics.median(ts),
    "min_ms": min(ts),
    "max_ms": max(ts),
    "n": N
}}))
"""


def main():
    print("=" * 70)
    print("  COLD INIT BENCHMARK — fork vs standard")
    print(f"  Branch: {_get_commit()}")
    print("=" * 70)
    print()

    results = {}

    # 1. Standard init
    print("[1/2] Standard cold init (StataSO_Main in fresh subprocess)")
    print(f"  ({N_WARMUP} warmup + {N_MEASURED} measured)")
    std_times = []
    for i in range(N_WARMUP + N_MEASURED):
        elapsed, out, err = run_script(STD_INIT, timeout=60)
        if "OK" not in out:
            print(f"    Run {i+1}: FAIL")
            continue
        if i >= N_WARMUP:
            std_times.append(elapsed)
        print(f"    Run {i+1}: {elapsed*1000:.1f} ms")

    if std_times:
        results["standard_init_ms"] = {
            "mean": statistics.mean(std_times) * 1000,
            "median": statistics.median(std_times) * 1000,
            "min": min(std_times) * 1000,
            "max": max(std_times) * 1000,
            "n": len(std_times),
        }

    # 2. Fork-based init
    print(f"\n[2/2] Fork-based cold init (from pre-initialized master)")
    print(f"  (100 forks)")
    fork_data = None
    elapsed, out, err = run_script(FORK_INIT, timeout=60)
    for line in out.strip().splitlines():
        if line.startswith("{"):
            fork_data = json.loads(line)
            break
    if fork_data:
        results["fork_init_ms"] = fork_data
        print(f"    Mean:   {fork_data['mean_ms']:.3f} ms")
        print(f"    Median: {fork_data['median_ms']:.3f} ms")
        print(f"    Min:    {fork_data['min_ms']:.3f} ms")
        print(f"    Max:    {fork_data['max_ms']:.3f} ms")

    # Comparison
    if std_times and fork_data:
        speedup = (statistics.median(std_times) * 1000) / fork_data["median_ms"]
        print(f"\n  Speedup: {speedup:.0f}x")
        print(f"    Standard: {statistics.median(std_times)*1000:.1f} ms")
        print(f"    Fork:     {fork_data['median_ms']:.2f} ms")
        results["speedup_vs_standard"] = speedup

    # Save
    hist_dir = REPO_ROOT / "benchmarks" / "history"
    hist_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    commit = _get_commit()
    dest = hist_dir / f"coldinit_fork_{ts}_{commit}.json"
    results["meta"] = {
        "timestamp": ts, "commit": commit,
        "machine": _machine(), "python": sys.version,
    }
    with open(dest, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n  Saved: {dest}")


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
