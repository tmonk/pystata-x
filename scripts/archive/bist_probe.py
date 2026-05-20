#!/usr/bin/env python3
"""
bist_probe.py — In-process calling convention discovery for _bist_* functions.

This script runs INSIDE the Python + Stata process (no lldb needed). It probes
a _bist_* function with different argument patterns and infers its calling
convention by reading the internal stack before/after each call.

Usage:
    python3 scripts/bist_probe.py _bist_data
    python3 scripts/bist_probe.py _bist_global
    python3 scripts/bist_probe.py --list

How it works:
  1. Initialises Stata (loads libstata-se.dylib).
  2. For the given _bist_* function, tries different argument patterns:
     - 0 args, 1 arg (int), 2 args (int, int), 1 (str), 1 (dbl), etc.
  3. Before each call, captures the internal stack pointer.
  4. After the call, reads the result from the stack (tsmat).
  5. Reports which argument patterns produce valid results vs crashes.
  6. For each pattern, shows register state (via internal registers at known offsets).
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent

sys.path.insert(0, str(_PROJECT_ROOT / "src"))
os.environ.setdefault(
    "STATA_LIB_PATH",
    str(Path("/tmp") / "libstata-traced.dylib")
    if (Path("/tmp") / "libstata-traced.dylib").exists()
    else "/Applications/StataNow/StataSE.app/Contents/MacOS/libstata-se.dylib",
)

# Initialise Stata
from pystata_x.sfi._engine import (
    initialize, execute, _BASE, _LIB, _SYMS,
    _arm64_push_int, _arm64_push_double, _arm64_push_str,
    _save_sp, _restore_sp,
    _arm64_pop_and_read_double, _arm64_pop_and_read_int,
    _arm64_pop_and_read_string,
    _STACK_PTR_OFFSET,
)
from pystata_x.sfi._manifest import discover_symbols

# Ensure Stata is initialised
initialize()
execute("sysuse auto, clear")


def load_manifest() -> dict:
    manifest_path = _PROJECT_ROOT / "src" / "pystata_x" / "sfi" / "manifest.json"
    if manifest_path.exists():
        with open(manifest_path) as f:
            return json.load(f)
    return {}


def find_symbol(manifest: dict, name: str) -> Optional[int]:
    syms = manifest.get("symbols", {})
    if name in syms:
        return syms[name]
    for k, v in syms.items():
        if k.startswith(name):
            return v
    for k, v in syms.items():
        if name in k:
            return v
    return None


def list_bist_symbols(manifest: dict, pattern: str = "_bist_") -> dict:
    return {k: v for k, v in manifest.get("symbols", {}).items()
            if k.startswith(pattern)}


# ── Probe helpers ──────────────────────────────────────────────────

def _raw_call(name: str) -> Optional[ctypes._CFuncPtr]:
    """Get a raw CFUNCTYPE(None) wrapper for a _bist_* function."""
    addr = _SYMS.get(name)
    if addr is None:
        return None
    return ctypes.cast(_BASE + addr, ctypes.CFUNCTYPE(None))


def probe_stack_after_call(name: str, push_fn=None) -> dict:
    """Probe a _bist_* function by optionally pushing args, calling it,
    and reading what's on Stata's internal stack afterwards.

    Returns a dict with:
      - pushed: whether args were pushed
      - sp_before / sp_after: stack pointer values
      - tsmat / data / value: the result if any
      - error: error code if available (at _BASE + 0x39b7000 + 0x11c)
    """
    result = {
        "name": name,
        "pushed": push_fn is not None,
        "sp_before": None,
        "sp_after": None,
        "tsmat": None,
        "data_ptr": None,
        "value": None,
        "error_code": None,
        "crashed": False,
    }

    fn = _raw_call(name)
    if fn is None:
        result["error"] = "symbol_not_found"
        return result

    try:
        sp_before = _save_sp()
        result["sp_before"] = sp_before

        if push_fn:
            push_fn()

        fn()
        sp_after = _save_sp()
        result["sp_after"] = sp_after

        # Read tsmat at SP
        if sp_after:
            tsmat = ctypes.c_uint64.from_address(sp_after).value
            result["tsmat"] = tsmat
            if tsmat:
                data_ptr = ctypes.c_uint64.from_address(tsmat).value
                result["data_ptr"] = data_ptr
                if data_ptr:
                    val = ctypes.c_double.from_address(data_ptr).value
                    result["value"] = val

        # Read error code (at _BASE + 0x39b7000 + 0x11c)
        err_addr = _BASE + 0x39b7000 + 0x11c
        result["error_code"] = ctypes.c_int.from_address(err_addr).value

        # Restore SP
        _restore_sp(sp_before)

    except Exception as e:
        result["crashed"] = True
        result["error_msg"] = str(e)

    return result


def probe_with_patterns(name: str) -> list[dict]:
    """Try a _bist_* function with various argument patterns.

    Patterns tested:
      0. No args (bare call)
      1. One int arg (0)
      2. Two int args (0, 0)
      3. One double arg (0.0)
      4. One string arg (b"test")
      5. One int arg (74 — obs count for auto.dta)
    """
    results = []

    patterns = [
        ("no_args", None),
        ("push_int(0)", lambda: _arm64_push_int(0)),
        ("push_int(0)+push_int(0)", lambda: (_arm64_push_int(0), _arm64_push_int(0))),
        ("push_int(1)+push_int(1)", lambda: (_arm64_push_int(1), _arm64_push_int(1))),
        ("push_dbl(0.0)", lambda: _arm64_push_double(0.0)),
        ("push_str('test')", lambda: _arm64_push_str(b"test")),
        ("push_int(74)", lambda: _arm64_push_int(74)),  # nobs in auto
        ("push_int(0)+push_int(1)", lambda: (_arm64_push_int(0), _arm64_push_int(1))),
        ("push_int(1)+push_int(0)", lambda: (_arm64_push_int(1), _arm64_push_int(0))),
        ("push_int(0)+push_int(0)+push_int(0)", lambda: (
            _arm64_push_int(0), _arm64_push_int(0), _arm64_push_int(0)
        )),
    ]

    for label, push_fn in patterns:
        r = probe_stack_after_call(name, push_fn)
        r["pattern"] = label
        results.append(r)

    return results


def print_probe_results(name: str, results: list[dict]):
    """Pretty-print probe results."""
    print("=" * 72)
    print(f"  PROBE: {name}")
    print(f"  _BASE = 0x{_BASE:x}")
    print(f"  Manifest addr: {_SYMS.get(name, 'NOT FOUND')}")
    print("=" * 72)

    for r in results:
        if r.get("crashed"):
            print(f"\n  ❌ {r['pattern']}: CRASHED — {r.get('error_msg', '')}")
            continue

        sp_before = r.get("sp_before")
        sp_after = r.get("sp_after")
        tsmat = r.get("tsmat")
        value = r.get("value")
        error_code = r.get("error_code")

        print(f"\n  [{r['pattern']}]")
        print(f"    SP: {sp_before} -> {sp_after}  (Δ={sp_after - sp_before if sp_before and sp_after else '?'})")
        print(f"    tsmat: {tsmat or '—'}")
        print(f"    data:  {r.get('data_ptr') or '—'}")
        print(f"    value: {value!r}")
        print(f"    error: {error_code}")

    print()


def main():
    parser = argparse.ArgumentParser(
        description="bist_probe.py — In-process _bist_* calling convention discoverer",
    )
    parser.add_argument("function", nargs="?", help="Function to probe")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--pattern", default="_bist_")
    args = parser.parse_args()

    if args.list:
        manifest = load_manifest()
        syms = list_bist_symbols(manifest, args.pattern)
        print(f"Symbols matching '{args.pattern}': ({len(syms)} total)")
        for name, addr in sorted(syms.items()):
            print(f"  {name}: {addr}")
        return

    if not args.function:
        parser.print_help()
        print("\nExamples:")
        print("  python3 scripts/bist_probe.py _bist_data")
        print("  python3 scripts/bist_probe.py _bist_global")
        print("  python3 scripts/bist_probe.py --list")
        return

    manifest = load_manifest()
    func_addr = find_symbol(manifest, args.function)
    if func_addr is None:
        print(f"[ERROR] '{args.function}' not found in manifest")
        for k in sorted(manifest.get("symbols", {})):
            if args.function in k:
                print(f"  Did you mean: {k}")
        sys.exit(1)

    name = args.function
    print(f"[bist] Probes for {name} (addr={func_addr:_})")

    # Quick check: does the function exist in SYMS?
    if name not in _SYMS:
        print(f"[ERROR] {name} not found in _SYMS")
        sys.exit(1)

    results = probe_with_patterns(name)
    print_probe_results(name, results)


if __name__ == "__main__":
    main()
