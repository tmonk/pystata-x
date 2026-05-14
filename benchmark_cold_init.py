#!/usr/bin/env python3
"""Measure Stata cold-start initialisation time.

Tests three scenarios:
1. Original pystata via stata_setup (baseline)
2. Our optimised init via src.stata_fast._config.init()
3. Our stata_setup drop-in
"""

# SPDX-FileCopyrightText: 2025 Thomas Monk <t.d.monk@lse.ac.uk>
# SPDX-License-Identifier: AGPL-3.0-only

from __future__ import annotations

import subprocess
import sys
import time

ORIGINAL_SCRIPT = '''
import sys
sys.path.insert(0, "/Applications/StataNow/utilities")
import stata_setup
stata_setup.config("/Applications/StataNow", "se", splash=False)
'''

OPTIMISED_SCRIPT = '''
import sys
sys.path.insert(0, "/Users/tom/projects/stata-fast/src")
import time
from src.stata_fast import _config as fast_config
fast_config.init("se", st_path="/Applications/StataNow", splash=False)
'''

OPTIMISED_SETUP_SCRIPT = '''
import sys
sys.path.insert(0, "/Users/tom/projects/stata-fast/src")
import time
from src.stata_fast.stata_setup import config
config("/Applications/StataNow", "se", splash=False)
'''


def run_subprocess(script: str, label: str, retries: int = 2) -> float:
    """Run *script* in a fresh subprocess and return elapsed seconds."""
    times = []
    for i in range(retries):
        t0 = time.monotonic()
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True,
            timeout=60,
        )
        elapsed = time.monotonic() - t0
        print(f"  {label} (run {i+1}): {elapsed:.2f}s  "
              f"{'OK' if result.returncode == 0 else 'FAILED: ' + result.stderr.strip()[:80]}")
        if result.returncode == 0:
            times.append(elapsed)
    if times:
        return min(times)
    return 0.0


def main():
    print("=" * 60)
    print("  Stata Cold Init Benchmark")
    print("=" * 60)
    print()

    print("  --- Original pystata via stata_setup ---")
    orig = run_subprocess(ORIGINAL_SCRIPT, "original stata_setup.config()")

    print("\n  --- Optimised _config.init() ---")
    opt = run_subprocess(OPTIMISED_SCRIPT, "optimised _config.init()", retries=2)

    print("\n  --- Optimised stata_setup ---")
    opt_setup = run_subprocess(OPTIMISED_SCRIPT, "optimised stata_setup.config()", retries=2)

    print("\n" + "=" * 60)
    print("  Summary")
    print("=" * 60)
    print(f"  Original pystata via stata_setup:         {orig:.2f}s" if orig else "  Original: FAILED")
    print(f"  Optimised _config.init():                  {opt:.2f}s" if opt else "  Optimised: FAILED")
    print(f"  Optimised stata_setup.config():            {opt_setup:.2f}s" if opt_setup else "  Optimised setup: FAILED")

    if orig and opt:
        speedup = orig / opt
        print(f"  Speedup (init):                            {speedup:.1f}x")


if __name__ == "__main__":
    main()
