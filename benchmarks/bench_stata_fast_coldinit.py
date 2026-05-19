#!/usr/bin/env python3
"""Benchmark cold init: measure StataSO_Main time (engine-only, no dlopen).

Usage:
    uv run python benchmarks/bench_stata_fast_coldinit.py

Outputs JSON with timing data and prints summary.
"""

import json
import statistics
import subprocess
import sys
import os
import time

OUT_DIR = os.path.join(os.path.dirname(__file__), "history")
os.makedirs(OUT_DIR, exist_ok=True)

# Number of iterations each running in a fresh subprocess
N = 100

results = {
    "benchmark": "cold_init_engine_only",
    "description": "Time for StataSO_Main with -q, no -pyexec (engine init only, excludes dlopen)",
    "timestamp": time.strftime("%Y%m%d_%H%M%S"),
    "git_commit": (
        subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, cwd=os.path.dirname(__file__) + "/.."
        ).stdout.strip() or "unknown"
    ),
    "n_iterations": N,
    "engine_init_ms": [],
}

SCRIPT = r"""
import sys, ctypes, os, time

lib = ctypes.cdll.LoadLibrary('%s')
lib.stata_load.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
lib.stata_load.restype = ctypes.c_void_p
lib.stata_init_engine.argtypes = [ctypes.c_void_p, ctypes.c_int]
lib.stata_init_engine.restype = ctypes.c_int

os.environ['SYSDIR_STATA'] = '/Applications/StataNow'
ctx = lib.stata_load(b'/Applications/StataNow', b'se')

t0 = time.perf_counter()
rc = lib.stata_init_engine(ctx, 0)
t1 = time.perf_counter()

init_ms = (t1 - t0) * 1000

# Verify it works
lib.stata_execute.argtypes = [
    ctypes.c_void_p,
    ctypes.c_char_p,
    ctypes.c_int,
    ctypes.POINTER(ctypes.c_char_p),
    ctypes.POINTER(ctypes.c_size_t),
    ctypes.POINTER(ctypes.c_int),
]
lib.stata_execute.restype = ctypes.c_int
lib.stata_free.argtypes = [ctypes.c_char_p]
lib.stata_free.restype = None

out_ptr = ctypes.c_char_p()
out_len = ctypes.c_size_t()
retcode = ctypes.c_int()
err = lib.stata_execute(ctx, b'display 1+1', 0,
                         ctypes.byref(out_ptr),
                         ctypes.byref(out_len),
                         ctypes.byref(retcode))
ok = (err == 0 and retcode.value == 0 and out_ptr.value == b'2\n')
if out_ptr.value:
    lib.stata_free(out_ptr)

print(f"RESULT|{init_ms:.3f}|{int(ok)}")
""" % "/Users/tom/projects/pystata-x/src/stata-fast/libstata_fast.dylib"

print(f"Running {N} iterations (each in a fresh subprocess)...")
for i in range(N):
    proc = subprocess.run(
        [sys.executable, "-c", SCRIPT],
        capture_output=True, text=True, timeout=30,
    )
    for line in proc.stdout.strip().split("\n"):
        if line.startswith("RESULT|"):
            parts = line.split("|")
            if len(parts) >= 3:
                init_ms = float(parts[1])
                ok = int(parts[2])
                if ok:
                    results["engine_init_ms"].append(init_ms)
                else:
                    print(f"  Iteration {i+1}: SKIP (smoke failed)")
                break
    if (i + 1) % 20 == 0:
        print(f"  {i+1}/{N}")

# Compute stats
ts = sorted(results["engine_init_ms"])
n = len(ts)
if n > 0:
    mid = n // 2
    median = ts[mid] if n % 2 else (ts[mid-1] + ts[mid]) / 2
    results["median_ms"] = median
    results["mean_ms"] = statistics.mean(ts)
    results["min_ms"] = min(ts)
    results["max_ms"] = max(ts)
    results["p90_ms"] = ts[int(n * 0.9)]
    results["p10_ms"] = ts[int(n * 0.1)]
    results["summary"] = (
        f"Engine init (StataSO_Main, -q, no -pyexec): "
        f"median={median:.3f} ms (N={n}) "
        f"target ≤12.5 ms: {'ACHIEVED' if median <= 12.5 else 'NOT ACHIEVED'}"
    )
else:
    results["summary"] = "No valid measurements"

# Save
timestamp = results["timestamp"]
out_path = os.path.join(OUT_DIR, f"coldinit_engine_{timestamp}.json")
with open(out_path, "w") as f:
    json.dump(results, f, indent=2)

print()
print(results["summary"])
print(f"  Mean:   {results.get('mean_ms', 0):.3f} ms")
print(f"  Min:    {results.get('min_ms', 0):.3f} ms")
print(f"  Max:    {results.get('max_ms', 0):.3f} ms")
print(f"  P10:    {results.get('p10_ms', 0):.3f} ms")
print(f"  P90:    {results.get('p90_ms', 0):.3f} ms")
print(f"  Saved:  {out_path}")
