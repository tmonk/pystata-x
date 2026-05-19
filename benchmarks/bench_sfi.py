#!/usr/bin/env python3
"""Benchmark pystata_x vs official sfi.py for all SFI methods.

This is the main benchmark runner.  For each SFI class, it measures:
- pystata_x method timing (in-process, after one-time init)
- official sfi.py method timing (via Stata python: subprocess)

Method groups:
1. **Cold start**: time from process launch to first SFI command
2. **Per-class microbenchmarks**: individual method timings
3. **Bulk operations**: dataset-level read/write patterns

Usage:
    uv run python benchmarks/bench_sfi.py                     # Full suite
    uv run python benchmarks/bench_sfi.py --class Data        # Single class
    uv run python benchmarks/bench_sfi.py --cold-only         # Cold start only
    uv run python benchmarks/bench_sfi.py --sfi-only          # Per-method only

Output: JSON to benchmarks/history/ with summary table
"""

import json
import math
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

# Find the benchmark dataset
DTA_CANDIDATES = sorted(DATA_DIR.glob("benchmark_*.dta"))
DTA_PATH = str(DTA_CANDIDATES[0]) if DTA_CANDIDATES else None

STATA_APP = "/Applications/StataNow/StataSE.app/Contents/MacOS/stata-se"
PYTHON = sys.executable

N_WARMUP = 3    # per benchmark function
N_MEASURED = 10  # per benchmark function


def git_commit():
    try:
        r = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                           capture_output=True, text=True, cwd=REPO_ROOT, timeout=5)
        return r.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


# ====================================================================
# COLD START BENCHMARK
# ====================================================================

def bench_cold_start():
    """Measure cold start time for pystata_x, official sfi, and native Stata."""
    results = {}

    def _stats_ms(times_ms):
        """Return stats dict from values already in ms."""
        if not times_ms:
            return {}
        s = sorted(times_ms)
        n = len(s)
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

    # 1. Native Stata CLI: process start → command done
    script = f"""
use "{DTA_PATH}", clear
summarize v001
display "READY"
exit, STATA
"""
    native_times = []
    for i in range(N_MEASURED):
        t0 = time.perf_counter()
        subprocess.run([STATA_APP, "-q", "do", "-"],
                       input=script.encode(), capture_output=True, timeout=30)
        t1 = time.perf_counter()
        native_times.append((t1 - t0) * 1000)
    results["native_stata_cli_ms"] = _stats_ms(native_times)

    # 2. pystata_x cold start: subprocess → import → init → SFI call
    px_script = f"""
import sys
sys.path.insert(0, {repr(str(SRC_DIR))})
from pystata_x.stata_setup import config
config('/Applications/StataNow', 'se', splash=False)
from pystata_x._core import run
run('use "{DTA_PATH}", clear', quietly=True)
from pystata_x.sfi._core import Data
nobs = Data.getObsTotal()
nvar = Data.getVarCount()
print(f"OK|{{nobs}}|{{nvar}}")
"""
    px_times = []
    for i in range(N_MEASURED):
        t0 = time.perf_counter()
        r = subprocess.run([PYTHON, "-c", px_script],
                           capture_output=True, text=True, timeout=30)
        t1 = time.perf_counter()
        px_times.append((t1 - t0) * 1000)
    results["pystata_x_cold_start_ms"] = _stats_ms(px_times)

    # 3. import-only time (excluding subprocess overhead)
    import_script = f"""
import sys
sys.path.insert(0, {repr(str(SRC_DIR))})
import pystata_x
print('OK')
"""
    import_times = []
    for i in range(N_MEASURED):
        t0 = time.perf_counter()
        r = subprocess.run([PYTHON, "-c", import_script],
                           capture_output=True, text=True, timeout=30)
        t1 = time.perf_counter()
        import_times.append((t1 - t0) * 1000)
    results["import_pystata_x_ms"] = _stats_ms(import_times)

    # 4. Official sfi import + first call (inside Stata Python)
    of_script = f"""
use "{DTA_PATH}", clear
python: import sfi
python: n = sfi.Data.getObsTotal()
python: print(f"OK|{{n}}")
exit, STATA
"""
    of_times = []
    for i in range(N_MEASURED):
        t0 = time.perf_counter()
        r = subprocess.run([STATA_APP, "-q", "do", "-"],
                           input=of_script.encode(), capture_output=True, timeout=30)
        t1 = time.perf_counter()
        of_times.append((t1 - t0) * 1000)
    results["official_sfi_cold_start_ms"] = _stats_ms(of_times)

    return results


# ====================================================================
# PER-CLASS / PER-METHOD MICROBENCHMARKS
# ====================================================================

# Each entry: (class_name, method_name, args_template, is_static)
# args_template is a dict of kwargs for the method call
# For official sfi, we'll convert these to Stata python: calls

SFI_BENCHMARKS = [
    # --- Data class ---
    ("Data", "getObsTotal", {}, True),
    ("Data", "getVarCount", {}, True),
    ("Data", "getVarName", {"varno": 0}, True),
    ("Data", "getVarLabel", {"varno": 0}, True),
    ("Data", "getVarType", {"varno": 0}, True),
    ("Data", "getVarIndex", {"name": "v001"}, True),
    ("Data", "getVarFormat", {"varno": 0}, True),
    ("Data", "getDouble", {"varno": 0, "obs": 0}, True),
    ("Data", "getString", {"varno": 26, "obs": 0}, True),  # s001 string var
    ("Data", "storeDouble", {"varno": 0, "obs": 0, "val": 42.0}, True),
    ("Data", "isVarTypeStr", {"varno": 26}, True),
    ("Data", "isVarTypeNumeric", {"varno": 0}, True),
    ("Data", "getStrVarWidth", {"varno": 0}, True),
    ("Data", "isAlias", {"varno": 0}, True),
    ("Data", "getMaxStrLength", {}, True),
    ("Data", "getMaxVars", {}, True),

    # --- Macro class ---
    ("Macro", "getGlobal", {"name": "c(current_date)"}, True),
    ("Macro", "setGlobal", {"name": "_test_macro", "value": "hello"}, True),
    ("Macro", "delGlobal", {"name": "_test_macro"}, True),
    ("Macro", "getLocal", {"name": "_test_macro"}, True),  # returns empty

    # --- Scalar class ---
    ("Scalar", "getValue", {"name": "c(level)"}, True),
    ("Scalar", "getString", {"name": "c(current_date)"}, True),

    # --- Missing class ---
    ("Missing", "isMissing", {"value": 0.0}, True),
    ("Missing", "getValue", {}, True),
    ("Missing", "getMissing", {}, True),
    ("Missing", "parseIsMissing", {"s": "."}, True),

    # --- ValueLabel class ---
    ("ValueLabel", "exists", {"name": "catlabels"}, True),
    ("ValueLabel", "getNames", {}, True),
    ("ValueLabel", "getLabel", {"name": "catlabels", "value": 1}, True),

    # --- SFIToolkit class ---
    ("SFIToolkit", "abbrev", {"name": "summarize", "n": 4}, True),
    ("SFIToolkit", "isValidName", {"name": "v001"}, True),
    ("SFIToolkit", "getTempName", {}, True),
    ("SFIToolkit", "getTempFile", {}, True),
    ("SFIToolkit", "macroExpand", {"macro_spec": "$S_level"}, True),
    ("SFIToolkit", "displayln", {"s": "hello"}, True),
    ("SFIToolkit", "error", {"rc": 1}, True),
    ("SFIToolkit", "formatValue", {"value": 123.456, "fmt": "%9.2f"}, True),
    ("SFIToolkit", "isFmt", {"fmt": "%9.2f"}, True),
    ("SFIToolkit", "isNumFmt", {"fmt": "%9.2f"}, True),
    ("SFIToolkit", "isStrFmt", {"fmt": "%9s"}, True),
    ("SFIToolkit", "strToName", {"s": "my variable name"}, True),
    ("SFIToolkit", "makeVarName", {"name": "my var"}, True),
    ("SFIToolkit", "pollnow", {}, True),
    ("SFIToolkit", "pollstd", {}, True),
]


def _px_call(cls_name, method_name, **kwargs):
    """Generate pystata_x call for a benchmark loop."""
    cls_path = f"pystata_x.sfi._core.{cls_name}"
    if not kwargs:
        return f"{cls_path}.{method_name}()"
    args = ", ".join(f"{k}={v!r}" for k, v in kwargs.items())
    return f"{cls_path}.{method_name}({args})"


def _of_call(cls_name, method_name, **kwargs):
    """Generate official sfi.py call string for Stata python: syntax."""
    if cls_name == "Data":
        # Some Data methods are static in both implementations
        call = f"sfi.{cls_name}.{method_name}("
    else:
        call = f"sfi.{cls_name}.{method_name}("
    if not kwargs:
        call += ")"
    else:
        args = ", ".join(f"{k}={v!r}" for k, v in kwargs.items())
        call += args + ")"
    return call


def run_px_benchmarks():
    """Run all per-method benchmarks via pystata_x in a single subprocess."""
    # Generate a comprehensive benchmark script
    setup = f"""
import sys, gc, time
sys.path.insert(0, {repr(str(SRC_DIR))})
from pystata_x.stata_setup import config
config('/Applications/StataNow', 'se', splash=False)
from pystata_x._core import run
run('use "{DTA_PATH}", clear', quietly=True)
from pystata_x.sfi._core import Data, Macro, Scalar, Missing, ValueLabel, SFIToolkit

n_warmup = {N_WARMUP}
n_measured = {N_MEASURED}
results = {{}}

def measure(fn, *args, **kwargs):
    # Warmup
    for _ in range(n_warmup):
        fn(*args, **kwargs)
    # Measured
    times = []
    for _ in range(n_measured):
        t0 = time.perf_counter()
        fn(*args, **kwargs)
        t1 = time.perf_counter()
        times.append((t1 - t0) * 1000 * 1000)  # microseconds
    return times  # keep raw for stats
"""

    benchmark_defs = []
    for cls_name, method_name, kwargs, is_static in SFI_BENCHMARKS:
        key = f"{cls_name}.{method_name}"
        if is_static:
            call = f"{cls_name}.{method_name}"
        else:
            call = f"{cls_name}().{method_name}"

        if not kwargs:
            benchmark_defs.append(
                f'results[{key!r}] = measure({call})'
            )
        else:
            args_repr = ", ".join(f"{k}={v!r}" for k, v in kwargs.items())
            benchmark_defs.append(
                f'results[{key!r}] = measure(lambda: {call}({args_repr}))'
            )

    script = setup + "\n" + "\n".join(benchmark_defs)
    script += "\nimport json; print(json.dumps(results))"

    r = subprocess.run([PYTHON, "-c", script],
                       capture_output=True, text=True, timeout=120)
    for line in r.stderr.split("\n"):
        if line.strip():
            print(f"  [stderr] {line}")
    if r.returncode != 0:
        print(f"  [ERROR] pystata_x benchmarks failed: {r.stdout[-500:]}")
        return {}

    for line in r.stdout.strip().split("\n"):
        if line.startswith("{"):
            data = json.loads(line)
            return data
    return {}


def run_of_benchmarks():
    """Run all per-method benchmarks via official sfi.py in Stata subprocess.

    Each benchmark group runs in a single Stata session (start → run → exit).
    """
    results = {}
    n_per_subprocess = 8  # Run multiple benchmark calls per Stata session

    # Group benchmarks
    groups = [SFI_BENCHMARKS[i:i + n_per_subprocess]
              for i in range(0, len(SFI_BENCHMARKS), n_per_subprocess)]

    for group_idx, group in enumerate(groups):
        calls_py = []
        calls_stata_define = []

        for cls_name, method_name, kwargs, is_static in group:
            key = f"{cls_name}.{method_name}"
            of_call_str = _of_call(cls_name, method_name, **kwargs)
            calls_py.append((key, of_call_str))

        # Build the Stata script
        script_lines = [f'use "{DTA_PATH}", clear']
        for key, call_str in calls_py:
            script_lines.append(f"""
python:
import time, json
n_warmup = {N_WARMUP}
n_measured = {N_MEASURED}
times = []
for _ in range(n_warmup):
    {call_str}
for _ in range(n_measured):
    t0 = time.perf_counter()
    {call_str}
    t1 = time.perf_counter()
    times.append((t1 - t0) * 1000 * 1000)
results["{key}"] = times
end
""")

        script_lines.append("""
python:
print("BENCH_JSON:" + json.dumps(results))
end
exit, STATA
""")

        script = "\n".join(script_lines)

        # Prepare results dict in Python preamble
        preamble = f"""
python:
results = {{}}
import sfi
import time
end
"""
        script = preamble + "\n" + "\n".join(script_lines[1:])

        r = subprocess.run([STATA_APP, "-q", "do", "-"],
                           input=script.encode(), capture_output=True, timeout=120)
        stdout = r.stdout.decode() if r.stdout else ""

        for line in stdout.split("\n"):
            if "BENCH_JSON:" in line:
                try:
                    data = json.loads(line.split("BENCH_JSON:", 1)[1])
                    for k, v in data.items():
                        # Convert to same format
                        if all(isinstance(x, (int, float)) for x in v):
                            results[k] = v
                except Exception:
                    pass

    return results


# ====================================================================
# HELPERS
# ====================================================================

def _stats(times_us: list) -> dict:
    """Compute statistics from a list of times in microseconds."""
    if not times_us:
        return {}
    n = len(times_us)
    s = sorted(times_us)
    return {
        "n": n,
        "mean_us": statistics.mean(s),
        "median_us": s[n // 2],
        "min_us": s[0],
        "max_us": s[-1],
        "p10_us": s[int(n * 0.1)],
        "p90_us": s[int(n * 0.9)],
        "std_us": statistics.stdev(s) if n > 1 else 0,
    }


def _stats_ms(times_ms: list) -> dict:
    """Compute statistics from a list of times in milliseconds."""
    stats = _stats(times_ms)
    # Convert us fields to ms
    for k in list(stats.keys()):
        if k.endswith("_us"):
            stats[k.replace("_us", "_ms")] = stats.pop(k)
    return stats


def _microseconds(times_s: list[float]) -> list[float]:
    """Convert seconds to microseconds."""
    return [t * 1_000_000 for t in times_s]


# ====================================================================
# MAIN
# ====================================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(description="SFI benchmark suite")
    parser.add_argument("--cold-only", action="store_true")
    parser.add_argument("--sfi-only", action="store_true")
    parser.add_argument("--class", dest="cls_filter", type=str, default=None)
    args = parser.parse_args()

    print("=" * 70)
    print("  PYSTATA-X SFI BENCHMARK SUITE")
    print(f"  Dataset: {DTA_PATH or 'NOT FOUND'}")
    print(f"  Iterations: {N_WARMUP} warmup + {N_MEASURED} measured")
    print("=" * 70)

    if DTA_PATH is None:
        print("ERROR: No benchmark dataset found. Run generate_dataset.py first")
        sys.exit(1)

    results = {
        "meta": {
            "timestamp": time.strftime("%Y%m%d_%H%M%S"),
            "git_commit": git_commit(),
            "dataset": DTA_PATH,
            "n_warmup": N_WARMUP,
            "n_measured": N_MEASURED,
        },
    }

    # Cold start
    if not args.sfi_only:
        print("\n[1/2] Cold start benchmarks...")
        results["cold_start"] = bench_cold_start()
        cs = results["cold_start"]
        ns = cs.get("native_stata_cli_ms", {}).get("median_ms", 0)
        px = cs.get("pystata_x_cold_start_ms", {}).get("median_ms", 0)
        imp = cs.get("import_pystata_x_ms", {}).get("median_ms", 0)
        of = cs.get("official_sfi_cold_start_ms", {}).get("median_ms", 0)
        print(f"  Native Stata CLI:     {ns:.1f} ms")
        print(f"  pystata_x (total):    {px:.1f} ms  (×{ns/px:.1f} vs native)")
        print(f"  pystata_x (import):   {imp:.1f} ms")
        print(f"  Official sfi (total): {of:.1f} ms")
        print(f"  10× target: {'ACHIEVED' if ns/px >= 10 else 'NOT ACHIEVED'}"
              f"  (needs pystata_x ≤ {ns/10:.1f} ms)")

    # Per-method benchmarks
    if not args.cold_only:
        print("\n[2/2] Per-SFI-method benchmarks...")

        print("  Running pystata_x methods...")
        px_methods = run_px_benchmarks()
        print(f"  Got {len(px_methods)} benchmark results")

        print("  Running official sfi.py methods...")
        of_methods = run_of_benchmarks()
        print(f"  Got {len(of_methods)} benchmark results")

        # Combine
        methods = {}
        all_keys = set(px_methods.keys()) | set(of_methods.keys())
        for key in sorted(all_keys):
            methods[key] = {
                "pystata_x_us": _stats(px_methods.get(key, [])),
                "official_sfi_us": _stats(of_methods.get(key, [])),
            }
            px_med = methods[key]["pystata_x_us"].get("median_us", 0)
            of_med = methods[key]["official_sfi_us"].get("median_us", 0)
            if of_med > 0 and px_med > 0:
                methods[key]["speedup_vs_official"] = of_med / px_med
            elif px_med > 0:
                methods[key]["speedup_vs_official"] = float("inf")
            else:
                methods[key]["speedup_vs_official"] = 0

        results["methods"] = methods

        # Summary table
        print("\n" + "-" * 70)
        print(f"  {'Method':<35s} {'pystata_x (μs)':<18s} {'sfi (μs)':<18s} {'Speedup':<10s}")
        print("-" * 70)
        for key in sorted(methods.keys()):
            m = methods[key]
            px = m["pystata_x_us"].get("median_us", 0)
            of = m["official_sfi_us"].get("median_us", 0)
            sp = m["speedup_vs_official"]
            sp_str = f"×{sp:.1f}" if sp > 0 and sp < float("inf") else "N/A"
            if px == 0:
                sp_str = "MISSING"
            px_str = f"{px:.1f}" if px > 0 else "N/A"
            of_str = f"{of:.1f}" if of > 0 else "N/A"
            print(f"  {key:<35s} {px_str:<18s} {of_str:<18s} {sp_str:<10s}")
        print("-" * 70)

        # Count methods where pystata_x is faster
        faster = sum(1 for m in methods.values()
                     if m["speedup_vs_official"] is not None
                     and m["speedup_vs_official"] >= 1)
        slower = sum(1 for m in methods.values()
                     if m["speedup_vs_official"] is not None
                     and 0 < m["speedup_vs_official"] < 1)
        missing = sum(1 for m in methods.values()
                      if m["pystata_x_us"].get("median_us", 0) == 0)
        print(f"\n  pystata_x faster: {faster}  slower: {slower}  missing: {missing}")

    # Save
    ts = results["meta"]["timestamp"]
    commit = results["meta"]["git_commit"]
    name_parts = ["bench_sfi"]
    if args.cold_only:
        name_parts.append("cold")
    if args.sfi_only:
        name_parts.append("sfi")
    out_path = HIST_DIR / f"{'_'.join(name_parts)}_{ts}_{commit}.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
