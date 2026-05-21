#!/usr/bin/env python3
"""Analyze a Stata dispatch function's protocol on x86_64.

Usage (inside Docker):
  python3 scripts/analyze_fn_protocol.py <func_name> [--output <path>]

This imports the _analyzer framework to:
1. Find the function's dispatch table entry
2. Follow thunk jumps to the implementation
3. Decompile key sections to understand the calling convention
4. Optionally run the function via the live engine to see what happens

All debugging flows through _analyzer.py — no ad-hoc scripts.
"""

import argparse
import json
import os
import sys

# Ensure we can import from the source
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def analyze_function(func_name: str, lib_path: str = "/usr/local/stata19/libstata-se.so",
                     output_path: str = None, run_test: bool = True) -> dict:
    from pystata_x.sfi._analyzer import StataBinary

    b = StataBinary(lib_path)
    b.analyze()

    result = {
        "name": func_name,
        "vaddr": None,
        "dispatch_idx": None,
        "disassembly_size": None,
        "calls_pushstr": None,
        "pool_header_check": None,
        "flag_field": None,
        "reads_sp": None,
        "error_codes": None,
        "sections": None,
        "protocol_type": None,
        "live_test": None,
    }

    # --- Static analysis via analyze_dispatch_fn ---
    try:
        fn_info = b.analyze_dispatch_fn(func_name)
        if fn_info:
            result.update(fn_info)
    except Exception as e:
        result["analyze_error"] = str(e)

    # --- Protocol analysis via analyze_protocol ---
    try:
        proto = b.analyze_protocol(func_name)
        if proto:
            for k, v in proto.items():
                if k != "name":
                    result[f"protocol_{k}"] = v
    except Exception as e:
        result["protocol_error"] = str(e)

    # --- Full disassembly ---
    addr = None
    if result.get("dispatch_idx") is not None and b.dispatch_entries:
        idx = result["dispatch_idx"]
        addr = b.dispatch_entries[idx]
        result["dispatch_entry_addr"] = hex(addr) if addr else None
    elif result.get("vaddr"):
        addr = result["vaddr"]

    if addr:
        try:
            # Disassemble with thunk following up to depth 3
            code, _, sections = b._follow_thunk(addr, max_depth=3, include_full=True)
            result["implementation_size"] = len(code)
            result["num_sections_after_jumps"] = len(sections) if sections else None
            result["disassembly"] = code
        except Exception as e:
            result["disasm_error"] = str(e)

    # --- Live engine test ---
    if run_test:
        try:
            test_result = _run_live_test(b, func_name)
            result["live_test"] = test_result
        except Exception as e:
            result["live_test_error"] = str(e)

    if output_path:
        with open(output_path, "w") as f:
            json.dump(result, f, indent=2, default=str)
        print(f"Result written to {output_path}")

    return result


def _run_live_test(b: "StataBinary", func_name: str) -> dict:
    """Run the function via the live engine and report results."""
    import ctypes

    from pystata_x.sfi._engine import (
        _BASE, _LIB, _get_fn, _read_stata_err, _restore_sp, _save_sp,
        _push_args, initialize, call_int, call_double, call_string, call_void,
    )

    initialize()
    _LIB.StataSO_Execute(b"sysuse auto, clear")

    test = {"attempts": []}

    # Try call_string (for string-returning functions)
    try:
        r = call_string(func_name, b"test_macro_call")
        test["attempts"].append({"method": "call_string", "arg": "test", "result": str(r)})
    except Exception as e:
        test["attempts"].append({"method": "call_string_error", "error": str(e)})

    # Try call_int with various arg types
    for arg in [1, b"make", b"origin"]:
        try:
            r = call_int(func_name, arg)
            test["attempts"].append({"method": "call_int", "arg": repr(arg), "result": r})
        except Exception as e:
            test["attempts"].append({"method": "call_int_error", "arg": repr(arg), "error": str(e)})

    # Try call_double
    for arg in [1.0, 0.0]:
        try:
            r = call_double(func_name, arg)
            test["attempts"].append({"method": "call_double", "arg": arg, "result": r})
        except Exception as e:
            test["attempts"].append({"method": "call_double_error", "arg": arg, "error": str(e)})

    # Try call_void
    try:
        call_void(func_name, b"test")
        rc = _read_stata_err()
        test["attempts"].append({"method": "call_void", "result": "ok", "error_rc": rc})
    except Exception as e:
        test["attempts"].append({"method": "call_void_error", "error": str(e)})

    return test


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Analyze dispatch function protocol")
    parser.add_argument("func_name", help="Function name (e.g., _bist_store)")
    parser.add_argument("--lib", default="/usr/local/stata19/libstata-se.so",
                        help="Path to libstata")
    parser.add_argument("--output", default=None, help="Output JSON path")
    parser.add_argument("--no-test", action="store_true", help="Skip live engine test")
    args = parser.parse_args()

    result = analyze_function(
        args.func_name,
        lib_path=args.lib,
        output_path=args.output,
        run_test=not args.no_test,
    )

    # Print summary
    print(f"\n=== Analysis: {args.func_name} ===")
    if result.get("dispatch_idx") is not None:
        print(f"  Dispatch index: {result['dispatch_idx']}")
    if result.get("vaddr"):
        print(f"  Vaddr: {hex(result['vaddr'])}")
    if result.get("implementation_size"):
        print(f"  Implementation size: {result['implementation_size']} bytes")
    if result.get("protocol_type"):
        print(f"  Protocol type: {result['protocol_type']}")
    if result.get("pool_header_check"):
        print(f"  Pool header check: {result['pool_header_check']}")
    if result.get("flag_field"):
        print(f"  Flag field: {result['flag_field']}")
    if result.get("error_codes"):
        print(f"  Error codes: {result['error_codes']}")
    if result.get("live_test"):
        print(f"  Live tests: {len(result['live_test']['attempts'])} attempts")
    if result.get("analyze_error"):
        print(f"  Analysis error: {result['analyze_error']}")
