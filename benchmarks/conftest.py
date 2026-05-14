"""Shared fixtures for the pystata-x benchmark suite."""

# SPDX-FileCopyrightText: 2025 Thomas Monk <t.d.monk@lse.ac.uk>
# SPDX-License-Identifier: AGPL-3.0-only

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

STATA_ROOT = "/Applications/StataNow"
STATA_EDITION = "se"
PYTHON = sys.executable
REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Helper: run a benchmark in a fresh subprocess
# ---------------------------------------------------------------------------

def subprocess_benchmark(
    setup_code: str,
    bench_fn: str,
    label: str,
    benchmark,
    min_time: float = 0.5,
    warmup: int = 3,
    timeout: int = 30,
) -> dict:
    """Run *bench_fn* in a fresh Python subprocess and measure with pytest-benchmark.

    This is the safe way to benchmark Stata operations because each
    Stata initialisation is process-bound.
    """

    def target():
        script = _make_script(setup_code, bench_fn, min_time, warmup)
        result = subprocess.run(
            [PYTHON, "-c", script],
            capture_output=True, text=True, timeout=timeout,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Subprocess failed: {result.stderr.strip()}")
        stats = _parse_output(result.stdout)
        return stats

    stats = benchmark(target)
    return stats


def _make_script(setup: str, bench: str, min_time: float, warmup: int) -> str:
    return f"""\
import math, statistics, time, sys

MIN_TIME = {min_time}
WARMUP = {warmup}

{setup}

times = []
for _ in range(WARMUP):
    {bench}

t_start = time.perf_counter()
while time.perf_counter() - t_start < MIN_TIME:
    t1 = time.perf_counter()
    {bench}
    times.append(time.perf_counter() - t1)

n = len(times)
if n == 0:
    print("ERROR:0 rounds")
    sys.exit(1)
mn = sum(times) / n * 1000
med = statistics.median(times) * 1000
sd = statistics.stdev(times) * 1000 if n >= 2 else 0.0
ops = n / sum(times)
print("MEAN:" + str(round(mn, 6)))
print("MEDIAN:" + str(round(med, 6)))
print("STDEV:" + str(round(sd, 6)))
print("MIN:" + str(min(times) * 1000))
print("MAX:" + str(max(times) * 1000))
print("ROUNDS:" + str(n))
print("OPS:" + str(round(ops, 1)))
"""


def _parse_output(stdout: str) -> float:
    """Return the mean execution time in milliseconds."""
    for line in stdout.strip().splitlines():
        if ":" in line:
            key, val = line.split(":", 1)
            if key.strip() == "MEAN":
                return float(val.strip())
    raise ValueError(f"No MEAN in output: {stdout[:200]}")


# ---------------------------------------------------------------------------
# pytest-benchmark history
# ---------------------------------------------------------------------------

def pytest_benchmark_update_json(config, benchmarks, output_json):
    hist_dir = Path(config.rootpath) / "benchmarks" / "history"
    hist_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    commit_info = "unknown"
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
            cwd=config.rootpath,
        )
        if result.returncode == 0:
            commit_info = result.stdout.strip()
    except Exception:
        pass

    filename = f"benchmark_{timestamp}_{commit_info}.json"
    dest = hist_dir / filename

    output_json.setdefault("meta", {})
    output_json["meta"].update({
        "timestamp": timestamp,
        "git_commit": commit_info,
        "project_root": str(config.rootpath),
    })

    with open(dest, "w") as f:
        json.dump(output_json, f, indent=2, default=str)
    print(f"\n[benchmark] Results saved to {dest}")
