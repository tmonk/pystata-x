"""
bist_capture.py — lldb Python helpers for _bist_* calling convention tracing.

Loaded into lldb via ``command script import``.

Provides two breakpoint callbacks:
  - ``init_handler`` — fires on StataSO_Initialize, detects libstata base,
    reads BIST_FUNC_NAME / BIST_FUNC_ADDR from env vars, sets _bist_ breakpoint.
  - ``_on_bist_hit`` — fires on _bist_ function, captures register/stack state.

Usage from lldb:
    (lldb) target create python3
    (lldb) settings set target.run-args test_script.py _bist_data
    (lldb) settings set target.env-vars \\
        BIST_FUNC_NAME=_bist_data \\
        BIST_FUNC_ADDR=1928428 \\
        BIST_MANIFEST=/path/to/manifest.json \\
        BIST_CAPTURE_DIR=/path/to/scripts \\
        STATA_LIB_PATH=/tmp/libstata-traced.dylib
    (lldb) command script import /path/to/bist_capture.py
    (lldb) breakpoint set --name StataSO_Initialize
    (lldb) breakpoint modify 1 --one-shot true
    (lldb) breakpoint command add -s python 1 -o "init_handler"
    (lldb) run

The bist_trace.py driver automates all the above.
"""
from __future__ import annotations

import json
import os
import sys
import textwrap
from typing import Optional


# ── Environment-based configuration ────────────────────────────────

def _get_config(key: str, default=None):
    """Read config from env vars (set via lldb `settings set target.env-vars`)."""
    return os.environ.get(key, default)


def init_handler(frame, bp_loc, internal_dict):
    """Called when StataSO_Main breakpoint fires (first Stata API call).

    The library is fully loaded at this point.  Reads config from env vars:
      BIST_FUNC_NAME  — function name (e.g. "_bist_data")
      BIST_FUNC_ADDR  — function manifest address offset
      BIST_MANIFEST   — path to manifest.json
      BIST_CAPTURE_DIR — path to directory containing bist_capture.py

    Then sets a _bist_ function breakpoint with _on_bist_hit callback.
    """
    import lldb

    func_name = _get_config("BIST_FUNC_NAME", "")
    func_addr_str = _get_config("BIST_FUNC_ADDR", "")
    manifest_path = _get_config("BIST_MANIFEST", "")
    capture_dir = _get_config("BIST_CAPTURE_DIR", "")

    if not func_name or not func_addr_str:
        print("[bist] ERROR: BIST_FUNC_NAME and BIST_FUNC_ADDR env vars required",
              file=sys.stderr)
        return

    func_addr = int(func_addr_str)
    target = frame.thread.process.target

    # Read manifest for symbol address (validate)
    bist_addr = func_addr
    if manifest_path:
        try:
            with open(manifest_path) as f:
                _manifest = json.load(f)
            manifest_addr = _manifest.get("symbols", {}).get(func_name)
            if manifest_addr is not None:
                bist_addr = manifest_addr
        except Exception as e:
            print(f"[bist] WARNING: could not read manifest: {e}", file=sys.stderr)

    # Find libstata and set _bist_ breakpoint
    for i in range(target.GetNumModules()):
        mod = target.GetModuleAtIndex(i)
        fn = mod.file.basename if mod.file else ""
        if "libstata" in fn.lower():
            for s in mod.sections:
                if s.name == "__TEXT":
                    base = s.GetLoadAddress(target)
                    actual = base + bist_addr
                    print(f"[bist] libstata __TEXT at 0x{base:x}", file=sys.stderr)
                    print(f"[bist] {func_name} at 0x{actual:x}", file=sys.stderr)

                    # Ensure capture module is importable
                    if capture_dir and capture_dir not in sys.path:
                        sys.path.insert(0, capture_dir)

                    # Set _bist_ breakpoint
                    bp = target.BreakpointCreateByAddress(actual)
                    bp.SetEnabled(True)
                    bp.SetOneShot(True)
                    bp.SetScriptCallbackFunction("bist_capture._on_bist_hit")
                    bp.AddName(func_name)
                    print(f"[bist] Breakpoint {bp.GetID()} set", file=sys.stderr)

                    # Also dump all loaded modules for debugging
                    print(f"[bist] Loaded modules:", file=sys.stderr)
                    for j in range(target.GetNumModules()):
                        m = target.GetModuleAtIndex(j)
                        mn = m.file.basename if m.file else "?"
                        print(f"  [{j}] {mn}", file=sys.stderr)

                    return

    print("[bist] WARNING: libstata module not found. Loaded modules:",
          file=sys.stderr)
    for i in range(target.GetNumModules()):
        m = target.GetModuleAtIndex(i)
        print(f"  [{i}] {m.file.basename if m.file else '?'}", file=sys.stderr)


def _on_bist_hit(frame, bp_loc, internal_dict):
    """Breakpoint callback for _bist_* function hit.

    Captures register state, call stack, and Stata internal stack.
    Prints a structured BIST TRACE block for parsing.
    """
    import lldb
    import struct

    thread = frame.thread
    bp_name = bp_loc.GetBreakpoint().GetName() or "unknown"

    state = {
        "pc": frame.pc,
        "registers": {},
        "floats": {},
        "stack": [],
        "caller": "",
        "frame2": "",
    }

    # Capture argument registers (x0-x7)
    for rname in ["x0", "x1", "x2", "x3", "x4", "x5", "x6", "x7"]:
        val = frame.FindRegister(rname)
        if val and val.IsValid():
            state["registers"][rname] = val.GetValue()

    # Other key registers
    for rname in ["fp", "lr", "sp", "pc", "x8", "x9", "x10", "x28"]:
        val = frame.FindRegister(rname)
        if val and val.IsValid():
            state["registers"][rname] = val.GetValue()

    # Float registers
    for rname in [f"d{i}" for i in range(8)]:
        val = frame.FindRegister(rname)
        if val and val.IsValid():
            state["floats"][rname] = val.GetValue()

    # Caller info
    if thread.num_frames > 1:
        f1 = thread.frames[1]
        state["caller"] = f1.name or hex(f1.pc)
    if thread.num_frames > 2:
        f2 = thread.frames[2]
        state["frame2"] = f2.name or hex(f2.pc)

    # Read stack (first 32 words from SP)
    sp_reg = frame.FindRegister("sp")
    if sp_reg and sp_reg.IsValid():
        sp = int(sp_reg.GetValue(), 16)
        error = lldb.SBError()
        try:
            mem = thread.process.ReadMemory(sp, 256, error)
            if error.Success() and mem:
                for i in range(0, min(len(mem), 256), 8):
                    w = int.from_bytes(mem[i:i+8], "little")
                    state["stack"].append(hex(w))
        except Exception:
            pass

    # Read Stata internal stack
    target = thread.process.target
    for i in range(target.GetNumModules()):
        mod = target.GetModuleAtIndex(i)
        fn = mod.file.basename if mod.file else ""
        if "libstata" in fn.lower():
            for s in mod.sections:
                if s.name == "__TEXT":
                    base = s.GetLoadAddress(target)
                    stata_sp_addr = base + 0x39b7000 + 0x108
                    error = lldb.SBError()
                    try:
                        stata_sp_mem = thread.process.ReadMemory(stata_sp_addr, 8, error)
                        if error.Success() and stata_sp_mem:
                            stata_sp = int.from_bytes(stata_sp_mem, "little")
                            state["stata_sp"] = hex(stata_sp)
                            tsmat_mem = thread.process.ReadMemory(stata_sp, 8, error)
                            if error.Success() and tsmat_mem:
                                tsmat = int.from_bytes(tsmat_mem, "little")
                                state["stata_tsmat"] = hex(tsmat)
                                if tsmat:
                                    data_mem = thread.process.ReadMemory(tsmat, 8, error)
                                    if error.Success() and data_mem:
                                        data_ptr = int.from_bytes(data_mem, "little")
                                        state["stata_data"] = hex(data_ptr)
                                        if data_ptr:
                                            dbl_mem = thread.process.ReadMemory(data_ptr, 8, error)
                                            if error.Success() and dbl_mem:
                                                state["stata_value"] = struct.unpack("<d", dbl_mem)[0]
                    except Exception:
                        pass
                    break
            break

    # Print the trace
    _print_state(state, bp_name)

    return False  # Don't stop


def _print_state(state: dict, name: str):
    """Pretty-print captured register/stack state."""
    print()
    print("=" * 72)
    print(f"  BIST TRACE: {name}")
    print(f"  PC: 0x{state.get('pc', 0):x}")
    print("=" * 72)

    caller = state.get("caller", "")
    if caller:
        print(f"  Caller:   {caller}")
    frame2 = state.get("frame2", "")
    if frame2:
        print(f"  Frame 2:  {frame2}")

    print()
    print("  ── Argument registers (x0-x7) ──")
    for r in ["x0", "x1", "x2", "x3", "x4", "x5", "x6", "x7"]:
        v = state["registers"].get(r, "")
        if v:
            try:
                as_int = int(v, 16)
                annotation = ""
                if as_int > 0x100000000:
                    annotation = " [PTR]"
                elif 0x20 <= as_int <= 0x7e:
                    annotation = f" '{chr(as_int)}'"
                print(f"    {r:>4s} = {v:>20s}  ({as_int:>12d}){annotation}")
            except (ValueError, TypeError):
                print(f"    {r:>4s} = {v:>20s}")

    print()
    print("  ── Float registers (d0-d7) ──")
    for r in [f"d{i}" for i in range(8)]:
        v = state["floats"].get(r, "")
        if v:
            print(f"    {r:>4s} = {v}")

    if state.get("stack"):
        print()
        print("  ── Stack at SP (first 32 words) ──")
        sp_val = int(state["registers"].get("sp", "0"), 16) if state["registers"].get("sp") else 0
        for i, w in enumerate(state["stack"][:32]):
            addr = sp_val + i * 8 if sp_val else 0
            try:
                as_int = int(w, 16)
                marker = ""
                if as_int > 0x100000000:
                    marker = " [PTR]"
                elif 0x20 <= as_int <= 0x7e:
                    marker = f" '{chr(as_int)}'"
                print(f"    SP+0x{i*8:03x} = {w:>20s}  (addr 0x{addr:x}){marker}")
            except (ValueError, TypeError):
                print(f"    SP+0x{i*8:03x} = {w:>20s}  (addr 0x{addr:x})")

    # Stata internal stack
    stata_sp = state.get("stata_sp")
    stata_tsmat = state.get("stata_tsmat")
    stata_data = state.get("stata_data")
    stata_value = state.get("stata_value")
    if stata_sp:
        print()
        print("  ── Stata internal stack / result ──")
        print(f"    stack_ptr (at _BASE+0x39b7000+0x108) = {stata_sp}")
        if stata_tsmat and stata_tsmat != "0x0":
            print(f"    *SP (tsmat pointer)   = {stata_tsmat}")
        if stata_data and stata_data != "0x0":
            print(f"    *(char**)tsmat[0]    = {stata_data}")
        if stata_value is not None:
            print(f"    *(double*)data       = {stata_value}")

    print("=" * 72)
    print()


def __lldb_init_module(debugger, internal_dict):
    print("[bist_capture] Loaded into lldbb.", file=sys.stderr)
    print("[bist_capture] Set BIST env vars, then breakpoint + run.", file=sys.stderr)


# ── Self-test (standalone) ─────────────────────────────────────────

if __name__ == "__main__":
    manifest_path = os.path.join(
        os.path.dirname(__file__), "..", "src", "pystata_x", "sfi", "manifest.json"
    )
    if os.path.exists(manifest_path):
        with open(manifest_path) as f:
            m = json.load(f)
        syms = m.get("symbols", {})
        print(f"Manifest: {len(syms)} symbols")
        for name in ["_bist_data", "_bist_global", "_bist_nobs", "_bist_varname",
                      "_bist_store", "_bist_sstore", "_bist_vlmap", "_bist_vlexists"]:
            print(f"  {name}: {syms.get(name, 'NOT FOUND')}")
    else:
        print(f"Manifest not at {manifest_path}")
