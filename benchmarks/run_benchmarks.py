#!/usr/bin/env python3
"""Comprehensive benchmark: pystata vs pystata-x.

Each benchmark case runs in a fresh subprocess that:
1. Initialises Stata once
2. Executes the benchmark function in a tight loop for >= MIN_TIME seconds
3. Reports mean/median timing

Usage:
    cd /Users/tom/projects/pystata-x

SPDX-FileCopyrightText: 2025 Thomas Monk <t.d.monk@lse.ac.uk>
SPDX-License-Identifier: AGPL-3.0-only
"""

from __future__ import annotations
    uv run python benchmarks/run_benchmarks.py
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
PYTHON = sys.executable
STATA_ROOT = "/Applications/StataNow"
STATA_EDITION = "se"
REPO_SRC = str(REPO_ROOT / "src")

MIN_TIME = 0.5  # seconds per benchmark
WARMUP = 3

# ---------------------------------------------------------------------------
# Script templates (each is a complete Python script run in a subprocess)
# ---------------------------------------------------------------------------

SCRIPTS: dict[str, str] = {}

# 1. pystata.stata.run — the original, full-stack path
SCRIPTS["pystata_run"] = f"""\
import sys, time, math, statistics as _stats
sys.path.insert(0, "{STATA_ROOT}/utilities")
import stata_setup
stata_setup.config("{STATA_ROOT}", "{STATA_EDITION}", splash=False)

from pystata.stata import run as _run

for _ in range({WARMUP}):
    _run("display 1+1", quietly=True)

_times = []
_t0 = time.perf_counter()
while time.perf_counter() - _t0 < {MIN_TIME}:
    _t1 = time.perf_counter()
    _run("display 1+1", quietly=True)
    _times.append(time.perf_counter() - _t1)

_n = len(_times)
_mn = sum(_times)/_n*1000
_md = _stats.median(_times)*1000
_sd = _stats.stdev(_times)*1000 if _n>=2 else 0.0
_ops = _n/sum(_times)
print(f"MEAN:{{_mn:.6f}}")
print(f"MEDIAN:{{_md:.6f}}")
print(f"STDEV:{{_sd:.6f}}")
print(f"MIN:{{min(_times)*1000}}")
print(f"MAX:{{max(_times)*1000}}")
print(f"ROUNDS:{{_n}}")
print(f"OPS:{{_ops:.1f}}")
"""

# 2. Raw StataSO_Execute — direct C API call (no streaming, no Python wrapper)
SCRIPTS["pystata_direct_sdk"] = f"""\
import sys, time, math, statistics as _stats
sys.path.insert(0, "{STATA_ROOT}/utilities")
import stata_setup
stata_setup.config("{STATA_ROOT}", "{STATA_EDITION}", splash=False)

from pystata import config as _cfg
_e = _cfg.stlib.StataSO_Execute
_en = _cfg.get_encode_str
_go = _cfg.get_output

for _ in range({WARMUP}):
    _cfg.stlib.StataSO_ClearOutputBuffer()
    _rc = _e(_en("display 1+1"), False)
    _out = _go() or ""

_times = []
_t0 = time.perf_counter()
while time.perf_counter() - _t0 < {MIN_TIME}:
    _t1 = time.perf_counter()
    _cfg.stlib.StataSO_ClearOutputBuffer()
    _rc = _e(_en("display 1+1"), False)
    _out = _go() or ""
    _times.append(time.perf_counter() - _t1)

_n = len(_times)
_mn = sum(_times)/_n*1000
_md = _stats.median(_times)*1000
_sd = _stats.stdev(_times)*1000 if _n>=2 else 0.0
_ops = _n/sum(_times)
print(f"MEAN:{{_mn:.6f}}")
print(f"MEDIAN:{{_md:.6f}}")
print(f"STDEV:{{_sd:.6f}}")
print(f"MIN:{{min(_times)*1000}}")
print(f"MAX:{{max(_times)*1000}}")
print(f"ROUNDS:{{_n}}")
print(f"OPS:{{_ops:.1f}}")
"""

# 3. pystata-x _core.run — our optimised wrapper
SCRIPTS["fast_run"] = f"""\
import sys, time, math, statistics as _stats
sys.path.insert(0, "{REPO_SRC}")
sys.path.insert(0, "{STATA_ROOT}/utilities")
import stata_setup
stata_setup.config("{STATA_ROOT}", "{STATA_EDITION}", splash=False)

from src.pystata_x._core import run as _run

for _ in range({WARMUP}):
    _run("display 1+1")

_times = []
_t0 = time.perf_counter()
while time.perf_counter() - _t0 < {MIN_TIME}:
    _t1 = time.perf_counter()
    _run("display 1+1")
    _times.append(time.perf_counter() - _t1)

_n = len(_times)
_mn = sum(_times)/_n*1000
_md = _stats.median(_times)*1000
_sd = _stats.stdev(_times)*1000 if _n>=2 else 0.0
_ops = _n/sum(_times)
print(f"MEAN:{{_mn:.6f}}")
print(f"MEDIAN:{{_md:.6f}}")
print(f"STDEV:{{_sd:.6f}}")
print(f"MIN:{{min(_times)*1000}}")
print(f"MAX:{{max(_times)*1000}}")
print(f"ROUNDS:{{_n}}")
print(f"OPS:{{_ops:.1f}}")
"""

# 4. pystata-x _core.run with quietly=True
SCRIPTS["fast_run_quietly"] = f"""\
import sys, time, math, statistics as _stats
sys.path.insert(0, "{REPO_SRC}")
sys.path.insert(0, "{STATA_ROOT}/utilities")
import stata_setup
stata_setup.config("{STATA_ROOT}", "{STATA_EDITION}", splash=False)

from src.pystata_x._core import run as _run

for _ in range({WARMUP}):
    _run("display 1+1", quietly=True)

_times = []
_t0 = time.perf_counter()
while time.perf_counter() - _t0 < {MIN_TIME}:
    _t1 = time.perf_counter()
    _run("display 1+1", quietly=True)
    _times.append(time.perf_counter() - _t1)

_n = len(_times)
_mn = sum(_times)/_n*1000
_md = _stats.median(_times)*1000
_sd = _stats.stdev(_times)*1000 if _n>=2 else 0.0
_ops = _n/sum(_times)
print(f"MEAN:{{_mn:.6f}}")
print(f"MEDIAN:{{_md:.6f}}")
print(f"STDEV:{{_sd:.6f}}")
print(f"MIN:{{min(_times)*1000}}")
print(f"MAX:{{max(_times)*1000}}")
print(f"ROUNDS:{{_n}}")
print(f"OPS:{{_ops:.1f}}")
"""

# 5. pystata-x _core.run with capture=False (fastest possible)
SCRIPTS["fast_run_nocapture"] = f"""\
import sys, time, math, statistics as _stats
sys.path.insert(0, "{REPO_SRC}")
sys.path.insert(0, "{STATA_ROOT}/utilities")
import stata_setup
stata_setup.config("{STATA_ROOT}", "{STATA_EDITION}", splash=False)

from src.pystata_x._core import run as _run

for _ in range({WARMUP}):
    _run("display 1+1", quietly=True, capture=False)

_times = []
_t0 = time.perf_counter()
while time.perf_counter() - _t0 < {MIN_TIME}:
    _t1 = time.perf_counter()
    _run("display 1+1", quietly=True, capture=False)
    _times.append(time.perf_counter() - _t1)

_n = len(_times)
_mn = sum(_times)/_n*1000
_md = _stats.median(_times)*1000
_sd = _stats.stdev(_times)*1000 if _n>=2 else 0.0
_ops = _n/sum(_times)
print(f"MEAN:{{_mn:.6f}}")
print(f"MEDIAN:{{_md:.6f}}")
print(f"STDEV:{{_sd:.6f}}")
print(f"MIN:{{min(_times)*1000}}")
print(f"MAX:{{max(_times)*1000}}")
print(f"ROUNDS:{{_n}}")
print(f"OPS:{{_ops:.1f}}")
"""

# 6. Multi-line: pystata
_ML_CODE = "\n".join([
    "sysuse auto, clear",
    "regress price mpg weight",
    "predict pred",
    "summarize pred",
])

_ML_BOILERPLATE_START = '''\
import sys, time, math, statistics as _stats
'''

_ML_BOILERPLATE_END = '''
_times = []
_t0 = time.perf_counter()
while time.perf_counter() - _t0 < {min_time}:
    _t1 = time.perf_counter()
    _run(_code)
    _times.append(time.perf_counter() - _t1)

_n = len(_times)
_mn = sum(_times)/_n*1000
_md = _stats.median(_times)*1000
_sd = _stats.stdev(_times)*1000 if _n>=2 else 0.0
_ops = _n/sum(_times)
print("MEAN:" + str(round(_mn, 6)))
print("MEDIAN:" + str(round(_md, 6)))
print("STDEV:" + str(round(_sd, 6)))
print("MIN:" + str(min(_times) * 1000))
print("MAX:" + str(max(_times) * 1000))
print("ROUNDS:" + str(_n))
print("OPS:" + str(round(_ops, 1)))
'''

PREAMBLE_PYSTATA = f'''
sys.path.insert(0, "{STATA_ROOT}/utilities")
import stata_setup
stata_setup.config("{STATA_ROOT}", "{STATA_EDITION}", splash=False)
from pystata.stata import run as _run
'''

PREAMBLE_FAST = f'''
sys.path.insert(0, "{REPO_SRC}")
sys.path.insert(0, "{STATA_ROOT}/utilities")
import stata_setup
stata_setup.config("{STATA_ROOT}", "{STATA_EDITION}", splash=False)
from pystata_x._core import run as _run
'''

# Use same call for both: _run(_code) without special flags
SCRIPTS["pystata_multiline"] = (
    _ML_BOILERPLATE_START
    + PREAMBLE_PYSTATA
    + '_code = """' + _ML_CODE + '"""\n'
    + f'for _ in range({WARMUP}):\n    _run(_code)\n'
    + _ML_BOILERPLATE_END.format(min_time=MIN_TIME * 2)
)

SCRIPTS["fast_multiline"] = (
    _ML_BOILERPLATE_START
    + PREAMBLE_FAST
    + '_code = """' + _ML_CODE + '"""\n'
    + f'for _ in range({WARMUP}):\n    _run(_code)\n'
    + _ML_BOILERPLATE_END.format(min_time=MIN_TIME * 2)
)

# 8. Echo: pystata
SCRIPTS["pystata_echo"] = f"""\
import sys, time, math, statistics as _stats
sys.path.insert(0, "{STATA_ROOT}/utilities")
import stata_setup
stata_setup.config("{STATA_ROOT}", "{STATA_EDITION}", splash=False)

from pystata.stata import run as _run

for _ in range({WARMUP}):
    _run("display 1+1", echo=True)

_times = []
_t0 = time.perf_counter()
while time.perf_counter() - _t0 < {MIN_TIME}:
    _t1 = time.perf_counter()
    _run("display 1+1", echo=True)
    _times.append(time.perf_counter() - _t1)

_n = len(_times)
_mn = sum(_times)/_n*1000
_md = _stats.median(_times)*1000
_sd = _stats.stdev(_times)*1000 if _n>=2 else 0.0
_ops = _n/sum(_times)
print(f"MEAN:{{_mn:.6f}}")
print(f"MEDIAN:{{_md:.6f}}")
print(f"STDEV:{{_sd:.6f}}")
print(f"MIN:{{min(_times)*1000}}")
print(f"MAX:{{max(_times)*1000}}")
print(f"ROUNDS:{{_n}}")
print(f"OPS:{{_ops:.1f}}")
"""

# 9. Echo: pystata-x
SCRIPTS["fast_echo"] = f"""\
import sys, time, math, statistics as _stats
sys.path.insert(0, "{REPO_SRC}")
sys.path.insert(0, "{STATA_ROOT}/utilities")
import stata_setup
stata_setup.config("{STATA_ROOT}", "{STATA_EDITION}", splash=False)

from src.pystata_x._core import run as _run

for _ in range({WARMUP}):
    _run("display 1+1", echo=True)

_times = []
_t0 = time.perf_counter()
while time.perf_counter() - _t0 < {MIN_TIME}:
    _t1 = time.perf_counter()
    _run("display 1+1", echo=True)
    _times.append(time.perf_counter() - _t1)

_n = len(_times)
_mn = sum(_times)/_n*1000
_md = _stats.median(_times)*1000
_sd = _stats.stdev(_times)*1000 if _n>=2 else 0.0
_ops = _n/sum(_times)
print(f"MEAN:{{_mn:.6f}}")
print(f"MEDIAN:{{_md:.6f}}")
print(f"STDEV:{{_sd:.6f}}")
print(f"MIN:{{min(_times)*1000}}")
print(f"MAX:{{max(_times)*1000}}")
print(f"ROUNDS:{{_n}}")
print(f"OPS:{{_ops:.1f}}")
"""

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

def run_script(name: str, script: str, timeout: int = 60) -> dict | None:
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    result = subprocess.run(
        [PYTHON, "-c", script],
        capture_output=True, text=True, timeout=timeout,
        env=env,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip()[:150]
        stdout = result.stdout.strip()[:150]
        print(f"  FAILED ({name}): {stderr or stdout}")
        return None
    stats = {}
    for line in result.stdout.strip().splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            try:
                stats[k.strip().lower()] = float(v.strip())
            except ValueError:
                pass
    if "mean" not in stats:
        print(f"  FAILED ({name}): no MEAN in output — {result.stdout.strip()[:100]}")
        return None
    return stats


def main():
    print("=" * 70)
    print("  pystata-x: Command Execution Benchmark")
    print("  Comparing original pystata vs optimised pystata-x")
    print("=" * 70)
    print()

    results = {}
    for name in sorted(SCRIPTS.keys()):
        print(f"  Running: {name} ... ", end="", flush=True)
        stats = run_script(name, SCRIPTS[name])
        if stats:
            results[name] = stats
            print(f"{stats['mean']:>8.3f} ms  ({stats['ops']:>8.0f} ops/s)")
        else:
            print("")

    # Summary
    print("\n" + "=" * 70)
    print("  Summary")
    print("=" * 70)
    print(f"  {'Test':<30} {'Mean (ms)':>10} {'Median (ms)':>10} {'Ops/s':>10}")
    print(f"  {'─'*30} {'─'*10} {'─'*10} {'─'*10}")
    for name in sorted(results.keys()):
        s = results[name]
        print(f"  {name:<30} {s['mean']:>10.3f} {s['median']:>10.3f} {s['ops']:>10.0f}")

    # Speedup comparison
    print()
    if "pystata_run" in results and "fast_run" in results:
        ratio = results["pystata_run"]["mean"] / results["fast_run"]["mean"]
        print(f"  Speedup (pystata_run vs fast_run): {ratio:.1f}x")
    if "pystata_direct_sdk" in results and "fast_run" in results:
        ratio2 = results["pystata_direct_sdk"]["mean"] / results["fast_run"]["mean"]
        print(f"  Speedup (direct SDK vs fast_run): {ratio2:.1f}x")
    if "pystata_multiline" in results and "fast_multiline" in results:
        ratio3 = results["pystata_multiline"]["mean"] / results["fast_multiline"]["mean"]
        print(f"  Speedup (multiline): {ratio3:.1f}x")
    if "pystata_echo" in results and "fast_echo" in results:
        ratio4 = results["pystata_echo"]["mean"] / results["fast_echo"]["mean"]
        print(f"  Speedup (echo=True): {ratio4:.1f}x")

    # Save results
    hist_dir = REPO_ROOT / "benchmarks" / "history"
    hist_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = hist_dir / f"benchmark_{timestamp}.json"
    with open(dest, "w") as f:
        json.dump({
            "timestamp": timestamp,
            "results": results,
            "machine": os.uname().machine,
        }, f, indent=2)
    print(f"\n  Results saved: {dest}")


if __name__ == "__main__":
    main()
