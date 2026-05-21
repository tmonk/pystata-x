#!/usr/bin/env python3
"""Comprehensive x86_64 dispatch function protocol analysis.

Runs inside Docker (where Stata is available). For each broken dispatch
function, it:
1. Gets the dispatch table entry and address
2. Follows thunk jumps to the implementation
3. Checks pool-header check pattern
4. Checks flag/type field expectations
5. Tests the function with live engine calls
6. Reports the correct protocol (what args, what return)

Outputs a JSON report to stdout.

Usage: python3 scripts/dispatch_analysis.py
"""

import json
import os
import sys
import struct
import ctypes

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from pystata_x.sfi._manifest import _read_elf_sections, build_manifest
from pystata_x.sfi._analyzer import StataBinary


def analyze_function(b: StataBinary, func_name: str, de: list) -> dict:
    """Analyze a single dispatch function."""
    result = {
        "name": func_name,
        "status": "unknown",
        "dispatch_idx": None,
        "thunk_addr": None,
        "impl_addr": None,
        "has_pool_check": None,
        "pool_check_offset": None,
        "flag_field": None,
        "checker_flags": None,
        "calls_pushstr": None,
        "protocol": None,
        "error_codes": [],
        "live_test_read": None,
        "live_test_write": None,
        "notes": [],
    }

    # --- Check if in symbol table ---
    sym_addr = b.symbols.get(func_name) if b.symbols else None
    if sym_addr is None:
        result["status"] = "not_in_manifest"
        return result

    result["thunk_addr"] = sym_addr

    # --- Find dispatch index ---
    for idx, addr in enumerate(de):
        if addr == sym_addr:
            result["dispatch_idx"] = idx
            break

    # --- Analyze dispatch fn ---
    try:
        fn_info = b.analyze_dispatch_fn(func_name)
        if fn_info:
            result["has_pool_check"] = fn_info.get("has_pool_header_check")
            if fn_info.get("error_code"):
                result["error_codes"].append(("thunk_entry", fn_info["error_code"]))
            if fn_info.get("flag_field"):
                result["flag_field"] = fn_info["flag_field"]
            result["caller_analysis"] = {k: v for k, v in fn_info.items()
                                         if k not in ("disassembly", "sections")}
    except Exception as e:
        result["notes"].append(f"analyze_dispatch_fn error: {e}")

    # --- Protocol analysis ---
    try:
        proto = b.analyze_protocol(func_name)
        if proto:
            result["protocol"] = proto
    except Exception as e:
        result["notes"].append(f"protocol error: {e}")

    # --- Follow thunk ---
    try:
        trace = b._follow_thunk(sym_addr, max_depth=3)
        # Find last address
        if trace:
            last = trace[-1][1]
            result["impl_addr"] = last
    except Exception as e:
        result["notes"].append(f"follow_thunk error: {e}")

    # --- Live engine test ---
    try:
        test = _live_test(b, func_name)
        result["live_test_read"] = test.get("read")
        result["live_test_write"] = test.get("write")
        if test.get("error"):
            result["notes"].append(f"live test error: {test['error']}")
    except Exception as e:
        result["notes"].append(f"live test exception: {e}")

    # --- Determine protocol type ---
    result["status"] = "analyzed"
    return result


def _live_test(b: StataBinary, func_name: str) -> dict:
    """Test function via live engine."""
    from pystata_x.sfi._engine import (
        _BASE, _LIB, _get_fn, _read_stata_err, _restore_sp, _save_sp,
        _push_str, _push_int, _push_double, initialize, call_int, call_double,
        call_string, call_void,
    )

    result = {"read": None, "write": None, "error": None}

    try:
        initialize()
        _LIB.StataSO_Execute(b"sysuse auto, clear")
    except Exception as e:
        result["error"] = f"init: {e}"
        return result

    # Test with call_string (string-returning functions)
    try:
        r = call_string(func_name, b"make")
        result["read"] = {"method": "call_string", "arg": "make", "result": r}
    except Exception as e:
        result["read"] = {"method": "call_string", "error": str(e)}

    # Test with call_double (numeric-returning functions)
    try:
        r = call_double(func_name, 1.0)
        if result["read"] is None:
            result["read"] = {"method": "call_double", "arg": 1.0, "result": r}
    except Exception as e:
        if result["read"] is None:
            result["read"] = {"method": "call_double", "error": str(e)}

    # Test with call_int
    try:
        r = call_int(func_name, 1)
        if result["read"] is None:
            result["read"] = {"method": "call_int", "arg": 1, "result": r}
    except Exception as e:
        if result["read"] is None:
            result["read"] = {"method": "call_int", "error": str(e)}

    # Test write path (2-3 arg)
    try:
        sp = _save_sp()
        _push_int(1)
        _push_int(1)
        _push_double(42.0)
        fn = _get_fn(_BASE + b.symbols.get(func_name, 0), None, ctypes.c_int)
        fn(3)
        rc = _read_stata_err()
        _restore_sp(sp)
        result["write"] = {"method": "3-arg", "rc": rc}
    except Exception as e:
        result["write"] = {"method": "3-arg", "error": str(e)}

    return result


def main():
    lib_path = os.environ.get("STATA_LIB_PATH", "/usr/local/stata19/libstata-se.so")

    b = StataBinary(lib_path)
    b.analyze()

    de = b.dispatch_entries
    if not de:
        print(json.dumps({"error": "No dispatch entries found"}))
        return

    # Functions to analyze
    funcs = [
        # String cell read/write
        "_bist_sdata",
        "_bist_sstore",
        # Numeric store
        "_bist_store",
        # Macro
        "_bist_global",
        # Scalars
        "_bist_numscalar",
        "_bist_strscalar",
        # Value labels
        "_bist_vlexists",
        "_bist_vlsearch",
        "_bist_vlmap",
        "_bist_vlmodify",
        "_bist_vldrop",
        "_bist_vlload",
        "_bist_varvaluelabel",
        # Variable metadata
        "_bist_varlabel",
        "_bist_varformat",
    ]

    results = {}
    for func_name in funcs:
        results[func_name] = analyze_function(b, func_name, de)
        print(f"  [{results[func_name]['status']:20s}] {func_name}", file=sys.stderr)

    print(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()
