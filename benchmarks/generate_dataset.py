#!/usr/bin/env python3
"""Generate a reproducible benchmark dataset as a Stata .dta file.

Creates a dataset with N observations and K variables (numeric + string),
saved to benchmarks/data/benchmark_dataset.dta for use by all benchmarks.

Usage:
    uv run python benchmarks/generate_dataset.py [--obs 100000] [--vars 30]

Output: benchmarks/data/benchmark_dataset.dta
"""

import argparse
import os
import pathlib
import random
import subprocess
import sys
import time
import struct

HERE = pathlib.Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
DATA_DIR.mkdir(exist_ok=True)

DEFAULT_OBS = 50_000
DEFAULT_VARS = 25


def main():
    parser = argparse.ArgumentParser(description="Generate benchmark dataset")
    parser.add_argument("--obs", type=int, default=DEFAULT_OBS,
                        help=f"Number of observations (default: {DEFAULT_OBS})")
    parser.add_argument("--vars", type=int, default=DEFAULT_VARS,
                        help=f"Number of numeric variables (default: {DEFAULT_VARS})")
    parser.add_argument("--seed", type=int, default=42, help="RNG seed")
    args = parser.parse_args()

    dta_path = DATA_DIR / f"benchmark_{args.obs}obs_{args.vars}vars.dta"
    dta_path = dta_path.resolve()

    random.seed(args.seed)

    print(f"Generating {args.obs} obs × {args.vars} vars benchmark dataset...")
    t0 = time.perf_counter()

    # Generate variables
    # Columns: id (int), v001-v{args.vars} (float/numeric), s001-s005 (string)
    n_str = 5
    total_cols = 1 + args.vars + n_str

    # Generate column names
    num_names = [f"v{i:03d}" for i in range(1, args.vars + 1)]
    str_names = [f"s{i:03d}" for i in range(1, n_str + 1)]
    col_names = ["id"] + num_names + str_names

    # Build data as list of lists for Stata do-file generation
    # We'll generate Stata code directly - much faster than CSV import
    # Use a simpler approach: generate minimal data via Stata

    stata_script = f"""
clear all
set obs {args.obs}
set seed {args.seed}
gen int id = _n
"""

    for i, name in enumerate(num_names):
        if i < 10:
            # Integer-like
            stata_script += f"gen {name} = runiformint(1, 10000)\n"
        elif i < 20:
            # Continuous normal
            stata_script += f"gen {name} = rnormal(50, 15)\n"
            stata_script += f"format {name} %9.4f\n"
        else:
            # Uniform with occasional missing
            stata_script += f"gen {name} = runiform(0, 100)\n"
            stata_script += f"format {name} %9.2f\n"
            # Add missing values - replace some random obs with .
            miss_pct = 5
            stata_script += f"replace {name} = . if runiform() < 0.{miss_pct:02d}\n"

    for name in str_names:
        stata_script += f"gen str6 {name} = \"cat\" + string(runiformint(1, 20))\n"

    # Add value labels for one variable as example
    stata_script += """
label define catlabels 1 "Low" 2 "Medium" 3 "High" 4 "Very High"
label values v001 catlabels

compress
"""

    # Drop the string indexing issue - use Stata to save
    stata_script += f"""save "{dta_path}", replace
describe
exit, STATA
"""

    proc = subprocess.run(
        ["/Applications/StataNow/StataSE.app/Contents/MacOS/stata-se",
         "-q", "do", "-"],
        input=stata_script.encode(),
        capture_output=True, timeout=120,
    )

    # Check for errors
    stderr_output = proc.stderr.decode() if proc.stderr else ""
    stdout_output = proc.stdout.decode() if proc.stdout else ""

    t1 = time.perf_counter()

    if not dta_path.exists():
        print(f"ERROR: DTA file not created. Stata output:")
        # Print last 20 lines of output
        lines = (stderr_output or stdout_output).split("\n")
        for line in lines[-25:]:
            print(f"  {line}")
        sys.exit(1)

    file_size = dta_path.stat().st_size
    print(f"Dataset generated: {dta_path}")
    print(f"  Size: {file_size / 1024 / 1024:.1f} MB")
    print(f"  Shape: {args.obs} obs × {args.vars} numeric + {n_str} string vars")
    print(f"  Time: {t1 - t0:.1f}s")


if __name__ == "__main__":
    main()
