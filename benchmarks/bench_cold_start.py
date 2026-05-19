#!/usr/bin/env python3
"""Cold-start benchmark: pystata_x vs official sfi.py vs native Stata CLI.

Measures time from process start to first successful SFI/Stata command.

Usage:
    uv run python benchmarks/bench_cold_start.py

Output: JSON results to benchmarks/history/
"""

import json
import os
import pathlib
import statistics
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
HIST_DIR = HERE / "history"
HIST_DIR.mkdir(exist_ok=True)

REPO_ROOT = HERE.parent
SRC_DIR = REPO_ROOT / "src"

DTA_PATH = list(DATA_DIR.glob("benchmark_*.dta"))
if DTA_PATH:
    DTA_PATH = str(DTA_PATH[0])
else:
    DTA_PATH = str(DATA_DIR / "benchmark_50000obs_25vars.dta")

STATA_APP = "/Applications/StataNow/StataSE.app/Contents/MacOS/stata-se"
N_ITERATIONS = 20


def git_commit():
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, cwd=REPO_ROOT,
        ).stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def run_native_stata_cold_start() -> list[float]:
    """Measure native Stata CLI cold start: launch → command completes."""
    results = []
    script = f"""
cap confirm file "{DTA_PATH}"
if _rc {{
    display "Dataset not found"
    exit 7
}}
use "{DTA_PATH}", clear
summarize v001
display "READY"
exit, STATA
"""
    for i in range(N_ITERATIONS):
        t0 = time.perf_counter()
        proc = subprocess.run(
            [STATA_APP, "-q", "do", "-"],
            input=script.encode(),
            capture_output=True, timeout=30,
        )
        t1 = time.perf_counter()
        ms = (t1 - t0) * 1000
        results.append(ms)
        if (i + 1) % 5 == 0:
            print(f"  Native Stata: {i+1}/{N_ITERATIONS}  ({ms:.1f} ms)")
    return results


def run_pystata_x_cold_start() -> list[float]:
    """Measure pystata_x cold start: import → first SFI command."""
    results = []
    setup = f"""
import sys, time
sys.path.insert(0, {repr(str(SRC_DIR))})

t0 = time.perf_counter()
from pystata_x.sfi._engine import _ensure_symbols, _find_lib
from pystata_x.stata_setup import initialize
lib_path = _find_lib()
_ensure_symbols(lib_path)
initialize(lib_path)
from pystata_x.sfi._core import Data
nobs = Data.getObsTotal()
t1 = time.perf_counter()
ms = (t1 - t0) * 1000
print(f"RESULT|{{ms:.3f}}|{{nobs}}")
"""
    for i in range(N_ITERATIONS):
        proc = subprocess.run(
            [sys.executable, "-c", setup],
            capture_output=True, text=True, timeout=30,
            env={**os.environ, "PYTHONPATH": str(SRC_DIR)},
        )
        for line in proc.stdout.strip().split("\n"):
            if line.startswith("RESULT|"):
                parts = line.split("|")
                ms = float(parts[1])
                nobs = int(parts[2])
                results.append(ms)
                break
        if (i + 1) % 5 == 0:
            print(f"  pystata_x:    {i+1}/{N_ITERATIONS}  ({ms:.1f} ms, nobs={nobs})")
    return results


def run_official_sfi_cold_start() -> list[float]:
    """Measure official sfi.py cold start: import sfi → first SFI command."""
    results = []
    for i in range(N_ITERATIONS):
        script = f"""
python: import time
python: t0 = time.perf_counter()
python: import sfi
python: n = sfi.Data.getObsTotal()
python: t1 = time.perf_counter()
python: ms = (t1 - t0) * 1000
python: print(f"RESULT|{{ms:.3f}}|{{n}}")
exit, STATA
"""
        proc = subprocess.run(
            [STATA_APP, "-q", "do", "-"],
            input=script.encode(),
            capture_output=True, timeout=30,
        )
        stdout = proc.stdout.decode() if proc.stdout else ""
        for line in stdout.split("\n"):
            if line.startswith("RESULT|"):
                parts = line.split("|")
                ms = float(parts[1])
                nobs = int(parts[2])
                results.append(ms)
                break
        if (i + 1) % 5 == 0:
            print(f"  Official sfi: {i+1}/{N_ITERATIONS}  ({ms:.1f} ms, nobs={nobs})")
    return results


def compute_stats(values: list[float]) -> dict:
    n = len(values)
    if n == 0:
        return {}
    s = sorted(values)
    return {
        "n": n,
        "mean_ms": statistics.mean(s),
        "median_ms": s[n // 2],
        "min_ms": s[0],
        "max_ms": s[-1],
        "p10_ms": s[int(n * 0.1)],
        "p90_ms": s[int(n * 0.9)],
        "std_ms": statistics.stdev(s) if n > 1 else 0,
    }


def main():
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    commit = git_commit()
    results = {
        "benchmark": "cold_start_sfi_comparison",
        "timestamp": timestamp,
        "git_commit": commit,
        "n_iterations": N_ITERATIONS,
        "dataset": DTA_PATH,
    }

    print("=" * 60)
    print("Cold Start Benchmarks")
    print(f"  Dataset: {DTA_PATH}")
    print(f"  Iterations: {N_ITERATIONS}")
    print("=" * 60)

    # 1. Native Stata CLI
    print("\n[1/3] Native Stata CLI cold start...")
    native = run_native_stata_cold_start()
    results["native_stata_cli"] = compute_stats(native)
    print(f"  Median: {results['native_stata_cli']['median_ms']:.1f} ms")

    # 2. pystata_x
    print("\n[2/3] pystata_x cold start (import + first SFI)...")
    pystata_x = run_pystata_x_cold_start()
    results["pystata_x"] = compute_stats(pystata_x)
    print(f"  Median: {results['pystata_x']['median_ms']:.1f} ms")

    # 3. Official sfi.py
    print("\n[3/3] Official sfi.py cold start...")
    official = run_official_sfi_cold_start()
    results["official_sfi"] = compute_stats(official)
    print(f"  Median: {results['official_sfi']['median_ms']:.1f} ms")

    # Speedup ratios
    ns = results["native_stata_cli"]["median_ms"]
    px = results["pystata_x"]["median_ms"]
    of = results["official_sfi"]["median_ms"]
    results["pystata_x_vs_native_speedup"] = ns / px if px > 0 else 0
    results["official_sfi_vs_native_speedup"] = ns / of if of > 0 else 0
    results["pystata_x_vs_official_speedup"] = of / px if px > 0 else 0

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  Native Stata CLI:     {ns:.1f} ms")
    print(f"  pystata_x:            {px:.1f} ms  (×{results['pystata_x_vs_native_speedup']:.1f} vs native)")
    print(f"  Official sfi.py:      {of:.1f} ms  (×{results['official_sfi_vs_native_speedup']:.1f} vs native)")
    print(f"  pystata_x vs official: ×{results['pystata_x_vs_official_speedup']:.1f}")
    print(f"  10× target: {'ACHIEVED' if results['pystata_x_vs_native_speedup'] >= 10 else 'NOT ACHIEVED'}")

    # Save
    out_path = HIST_DIR / f"coldstart_{timestamp}_{commit}.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
