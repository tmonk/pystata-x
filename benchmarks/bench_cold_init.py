#!/usr/bin/env python3
"""Cold-start initialisation benchmark for pystata-x.

Measures total subprocess wall time from ``python -c "import pystata_x.stata_setup; config(...)"``
and also instruments individual init phases via an instrumented subprocess.

Usage:
    uv run python benchmarks/bench_cold_init.py
"""

# SPDX-FileCopyrightText: 2025 Thomas Monk <t.d.monk@lse.ac.uk>
# SPDX-License-Identifier: AGPL-3.0-only

from __future__ import annotations

import json
import os
import platform as _platform
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

N_WARMUP = 3
N_MEASURED = 10

_ENV = os.environ.copy()
_ENV["PYTHONUNBUFFERED"] = "1"

# ---------------------------------------------------------------------------
# 1. Total cold-start time (subprocess wall clock)
# ---------------------------------------------------------------------------

TOTAL_SCRIPT = f"""\
import sys
sys.path.insert(0, "{REPO_SRC}")
from pystata_x.stata_setup import config
config("{STATA_ROOT}", "{STATA_EDITION}", splash=False)
print("OK")
"""


def measure_total() -> list[float]:
    """Return list of wall-clock times for cold-start subprocess."""
    times: list[float] = []
    for i in range(N_WARMUP + N_MEASURED):
        t0 = time.perf_counter()
        result = subprocess.run(
            [PYTHON, "-c", TOTAL_SCRIPT],
            capture_output=True, text=True, timeout=30,
            env=_ENV,
        )
        elapsed = time.perf_counter() - t0
        if result.returncode != 0:
            print(f"  Run {i+1}: FAILED — {result.stderr.strip()[:120]}")
            continue
        if i >= N_WARMUP:
            times.append(elapsed)
        status = f"{'OK' if result.returncode == 0 else 'FAIL'}"
        prefix = "Warmup" if i < N_WARMUP else f"Run {i-N_WARMUP+1}"
        print(f"  {prefix} {i+1}: {elapsed*1000:.1f} ms  [{status}]")
    return times


# ---------------------------------------------------------------------------
# 2. Phase-instrumented init (single subprocess, records phase times)
#
# NOTE: runs with PYTHONUNBUFFERED=1 so that per-phase output is visible and
# we can parse the JSON timing line reliably.
# ---------------------------------------------------------------------------

def _phase_script(first_run: bool) -> str:
    """Return a Python script that instruments each init phase.

    If *first_run* is True, it measures a truly cold start with no
    pre-imported modules. If False, it runs init again to measure
    the warm (idempotent) call.
    """
    if first_run:
        # Cold-first-run measurement: import each module from scratch,
        # measuring the time of each step.
        return f"""\
import sys, json, time

sys.path.insert(0, "{REPO_SRC}")

_timings = {{}}
_t0 = time.perf_counter()

# --- Phase 0: Python interpreter overhead (pre-script) ---
# We capture perf_counter as early as possible

# Phase 1: stdlib imports
_ts = time.perf_counter()
import ctypes, os, platform as _platform
_timings["stdlib_imports"] = time.perf_counter() - _ts

# Phase 2: import pystata_x._config
_ts = time.perf_counter()
from pystata_x import _config
_timings["import__config"] = time.perf_counter() - _ts

# Phase 3: _find_lib resolution
_ts = time.perf_counter()
lib_path = _config._find_lib("{STATA_ROOT}", "{STATA_EDITION}", _platform.system())
_timings["find_lib"] = time.perf_counter() - _ts

# Phase 4: cdll.LoadLibrary
_ts = time.perf_counter()
_config.stlib = ctypes.cdll.LoadLibrary(lib_path)
_timings["load_library"] = time.perf_counter() - _ts

# Phase 5: _init_stata (StataSO_Main) — this is the C-level engine bootstrap
_ts = time.perf_counter()
_config._init_stata(splash=False)
_timings["init_stata_main"] = time.perf_counter() - _ts

# Phase 6: get_output (drain buffer — may contain splash/license message)
_ts = time.perf_counter()
msg = _config.get_output()
_timings["get_output"] = time.perf_counter() - _ts

# Phase 7: import sfi + version query
_ts = time.perf_counter()
try:
    import sfi
    ver = str(sfi.Scalar.getValue("c(stata_version)"))
    _timings["sfi_version_query"] = time.perf_counter() - _ts
except Exception as e:
    _timings["sfi_version_query"] = time.perf_counter() - _ts
    _timings["sfi_error"] = str(e)

_t1 = time.perf_counter()
_timings["script_elapsed"] = _t1 - _t0

print("PYSTATA_X_TIMINGS:" + json.dumps(_timings))
"""
    else:
        # Warm call: init() is idempotent, measures the short-circuit path
        return f"""\
import sys, json, time

sys.path.insert(0, "{REPO_SRC}")
sys.path.insert(0, "{STATA_ROOT}/utilities")
from pystata_x.stata_setup import config
config("{STATA_ROOT}", "{STATA_EDITION}", splash=False)

_timings = {{}}
_ts = time.perf_counter()
from pystata_x.stata_setup import config
config("{STATA_ROOT}", "{STATA_EDITION}", splash=False)
_timings["warm_init"] = time.perf_counter() - _ts

# Also measure a basic command
_ts = time.perf_counter()
from pystata_x._core import execute
result = execute("display 1+1", quietly=True)
_timings["first_command"] = time.perf_counter() - _ts

print("PYSTATA_X_TIMINGS:" + json.dumps(_timings))
"""


def run_phase_script(first_run: bool) -> dict[str, float] | None:
    """Run the phase timing script, return the timings dict."""
    code = _phase_script(first_run)
    result = subprocess.run(
        [PYTHON, "-c", code],
        capture_output=True, text=True, timeout=30,
        env=_ENV,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip()[:200]
        stdout = result.stdout.strip()[:200]
        print(f"    FAILED (rc={result.returncode}): {stderr or stdout}")
        return None
    for line in result.stdout.strip().splitlines():
        if line.startswith("PYSTATA_X_TIMINGS:"):
            return json.loads(line[len("PYSTATA_X_TIMINGS:"):])
    print(f"    FAILED: no PYSTATA_X_TIMINGS line in output: {result.stdout.strip()[:200]}")
    return None


# ---------------------------------------------------------------------------
# 3. main
# ---------------------------------------------------------------------------

def _avg(records: list[dict], key: str) -> float:
    return statistics.mean([r[key] for r in records]) * 1000  # ms


def _med(records: list[dict], key: str) -> float:
    return statistics.median([r[key] for r in records]) * 1000  # ms


def _fmt_ms(seconds: float) -> str:
    return f"{seconds*1000:.1f}"


def main():
    print("=" * 70)
    print("  pystata-x: Cold-Start Init Benchmark")
    print(f"  Branch: {_get_commit()}")
    print("=" * 70)
    print()

    # --- Total wall time (subprocess) ---
    print("  [1/3] Total cold-start subprocess time")
    print(f"  ({N_WARMUP} warmup + {N_MEASURED} measured runs)")
    print()
    total_times = measure_total()
    if not total_times:
        print("  NO VALID TOTAL MEASUREMENTS — aborting")
        return

    print(f"\n  Total cold-start (subprocess wall clock):")
    print(f"    Min:     {_fmt_ms(min(total_times))} ms")
    print(f"    Median:  {_fmt_ms(statistics.median(total_times))} ms")
    print(f"    Mean:    {_fmt_ms(statistics.mean(total_times))} ms")
    print(f"    Max:     {_fmt_ms(max(total_times))} ms")
    if len(total_times) >= 2:
        print(f"    StdDev:  {_fmt_ms(statistics.stdev(total_times))} ms")

    # --- Cold-first-run phase breakdown ---
    print(f"\n  [2/3] Cold-first-run phase breakdown ({N_MEASURED} runs)")
    print()
    cold_records: list[dict] = []
    for i in range(N_WARMUP + N_MEASURED):
        label = "Warmup" if i < N_WARMUP else f"Run {i-N_WARMUP+1}"
        sys.stdout.write(f"    {label}... ")
        sys.stdout.flush()
        data = run_phase_script(first_run=True)
        if data is not None:
            if i >= N_WARMUP:
                cold_records.append(data)
            total_ms = data.get("script_elapsed", 0) * 1000
            print(f"{total_ms:.1f} ms")
        else:
            print("")

    if not cold_records:
        print("  NO VALID PHASE MEASUREMENTS")
        return

    phases = [
        ("stdlib imports", "stdlib_imports"),
        ("import _config", "import__config"),
        ("find_lib", "find_lib"),
        ("cdll.LoadLibrary", "load_library"),
        ("StataSO_Main", "init_stata_main"),
        ("get_output", "get_output"),
        ("sfi + ver query", "sfi_version_query"),
    ]

    # Compute grand total as the sum of phase means (should approximate script_elapsed)
    grand_total_ms = _avg(cold_records, "script_elapsed")

    print()
    print(f"  {'Phase':<25} {'Mean (ms)':>10} {'Median (ms)':>10} {'% of total':>10}")
    print(f"  {'─'*25} {'─'*10} {'─'*10} {'─'*10}")

    phase_sum_ms = 0.0
    for label, key in phases:
        if all(key in r for r in cold_records):
            am = _avg(cold_records, key)
            md = _med(cold_records, key)
            pct = (am / grand_total_ms * 100) if grand_total_ms > 0 else 0
            phase_sum_ms += am
            print(f"  {label:<25} {am:>10.2f} {md:>10.2f} {pct:>9.1f}%")

    # Account for unmeasured overhead (Python startup before our first phase, etc.)
    unmeasured = grand_total_ms - phase_sum_ms
    unmeasured_pct = (unmeasured / grand_total_ms * 100) if grand_total_ms > 0 else 0
    print(f"  {'─'*25} {'─'*10} {'─'*10} {'─'*10}")
    print(f"  {'Sum of phases':<25} {phase_sum_ms:>10.2f}")
    print(f"  {'Unmeasured (overhead)':<25} {unmeasured:>10.2f} {unmeasured_pct:>9.1f}%")
    print(f"  {'Script elapsed':<25} {grand_total_ms:>10.2f}")

    # --- Warm init (idempotent call) ---
    print(f"\n  [3/3] Warm init (idempotent 2nd call, {N_MEASURED} runs)")
    print()
    warm_records: list[float] = []
    warm_cmd_records: list[float] = []
    for i in range(N_WARMUP + N_MEASURED):
        label = "Warmup" if i < N_WARMUP else f"Run {i-N_WARMUP+1}"
        sys.stdout.write(f"    {label}... ")
        sys.stdout.flush()
        data = run_phase_script(first_run=False)
        if data is not None:
            if i >= N_WARMUP:
                warm_records.append(data.get("warm_init", 0))
                warm_cmd_records.append(data.get("first_command", 0))
            print(f"init={data.get('warm_init', 0)*1000:.3f} ms, " 
                  f"cmd={data.get('first_command', 0)*1000:.3f} ms")
        else:
            print("")

    if warm_records:
        print(f"\n  Warm init time:")
        print(f"    Mean:   {statistics.mean(warm_records)*1000:.3f} ms")
        print(f"    Median: {statistics.median(warm_records)*1000:.3f} ms")
    if warm_cmd_records:
        print(f"  First command after init:")
        print(f"    Mean:   {statistics.mean(warm_cmd_records)*1000:.3f} ms")
        print(f"    Median: {statistics.median(warm_cmd_records)*1000:.3f} ms")

    # --- Save ---
    hist_dir = REPO_ROOT / "benchmarks" / "history"
    hist_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    commit = _get_commit()
    dest = hist_dir / f"cold_init_{timestamp}_{commit}.json"
    with open(dest, "w") as f:
        json.dump({
            "timestamp": timestamp,
            "commit": commit,
            "total_subprocess_ms": {
                "min": min(total_times) * 1000,
                "median": statistics.median(total_times) * 1000,
                "mean": statistics.mean(total_times) * 1000,
                "max": max(total_times) * 1000,
                "stdev": statistics.stdev(total_times) * 1000 if len(total_times) >= 2 else 0,
                "n": len(total_times),
            },
            "phases": {
                k: {
                    "mean_ms": _avg(cold_records, k) if all(k in r for r in cold_records) else None,
                    "median_ms": _med(cold_records, k) if all(k in r for r in cold_records) else None,
                }
                for k in [k for _, k in phases]
            },
            "machine": _platform.machine(),
            "python": sys.version,
        }, f, indent=2)
    print(f"\n  Results saved: {dest}")


def _get_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
            cwd=REPO_ROOT,
        )
        return result.stdout.strip() if result.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


if __name__ == "__main__":
    main()
