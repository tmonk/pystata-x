#!/usr/bin/env python3
"""
Capture state script invoked by lldb's 'script' command on breakpoint hit.
Uses global variables set by lldb: frame, bp_loc, etc.

Also defines helper functions for manual lldb invocation.
"""

import json
import os
import struct
import sys

STACK_PTR_OFFSET = 0x39b7000 + 0x108
ERR_CODE_OFFSET = 0x39b7000 + 0x11c

CAPTURES = []
MANIFEST = None
OUTPUT_FILE = "/tmp/lldb_capture.json"

def load_manifest():
    global MANIFEST
    if MANIFEST is not None:
        return MANIFEST
    for path in [
        "src/pystata_x/sfi/manifest.json",
        os.path.join(os.path.dirname(__file__), "..", "src", "pystata_x", "sfi", "manifest.json"),
        os.path.expanduser("~/projects/pystata-x/src/pystata_x/sfi/manifest.json"),
    ]:
        abspath = os.path.abspath(path)
        if os.path.exists(abspath):
            with open(abspath) as f:
                MANIFEST = json.load(f)
            return MANIFEST
    return {"symbols": {}}


def compute_base(frame):
    """Compute _BASE from the current frame's PC and the manifest offset."""
    pc = frame.GetPC()
    if not pc:
        return 0
    manifest = load_manifest()
    # Find which function we're at by checking all offsets
    for fn_name, offset in manifest["symbols"].items():
        if fn_name.startswith("_"):
            test_base = pc - offset
            if 0 <= test_base < 0xfffffffffff:
                return test_base
    return 0


def capture_at_breakpoint(frame, bp_loc, extra_args, internal_dict):
    """Capture state at a breakpoint hit. Returns False (continue)."""
    process = frame.GetProcess()
    target = process.GetTarget()
    thread = frame.GetThread()

    bp_id = bp_loc.GetBreakpoint().GetID() if bp_loc else 0

    # Get registers
    regs = {}
    for name in ["x0", "x1", "x2", "x3", "x4", "x5", "x6", "x7", "x8",
                  "w0", "sp", "pc", "lr", "fp"]:
        try:
            r = frame.FindRegister(name)
            if r:
                regs[name] = r.GetValueAsUnsigned()
        except:
            pass

    pc = regs.get("pc", 0)
    base_addr = compute_base(frame)

    # Find function name
    manifest = load_manifest()
    fn_name = "unknown"
    fn_offset = 0
    if base_addr and pc:
        fn_offset = pc - base_addr
        for n, off in manifest["symbols"].items():
            if off == fn_offset:
                fn_name = n
                break

    capture = {
        "function": fn_name,
        "pc": pc,
        "fn_offset": fn_offset,
        "base_addr": base_addr,
        "registers": regs,
        "stata_state": {},
        "memory": {},
    }

    # Read Stata internal state
    if base_addr:
        internal_sp_addr = base_addr + STACK_PTR_OFFSET
        err_addr = base_addr + ERR_CODE_OFFSET

        try:
            internal_sp = process.ReadUnsignedFromMemory(internal_sp_addr, 8, lldb.SBError())
            capture["stata_state"]["internal_sp_addr"] = internal_sp_addr
            capture["stata_state"]["internal_sp"] = internal_sp

            # Read 128 bytes around internal SP
            stack_read_addr = max(0, internal_sp - 48) if internal_sp > 48 else internal_sp
            stack_bytes = process.ReadMemory(stack_read_addr, 128, lldb.SBError())
            if stack_bytes and len(stack_bytes) > 0:
                vals = []
                for i in range(0, min(len(stack_bytes), 128), 8):
                    chunk = stack_bytes[i:i+8]
                    if len(chunk) == 8:
                        vals.append(hex(struct.unpack("<Q", chunk)[0]))
                capture["memory"]["internal_stack_vals"] = vals

            # Read error code
            err_val = process.ReadUnsignedFromMemory(err_addr, 4, lldb.SBError())
            capture["stata_state"]["err_code"] = err_val

            # Read tsmat at current internal SP
            if internal_sp:
                tsmat_ptr = process.ReadUnsignedFromMemory(internal_sp, 8, lldb.SBError())
                capture["stata_state"]["tsmat_at_sp"] = tsmat_ptr
                if tsmat_ptr and tsmat_ptr > 0x100000:
                    try:
                        tsmat_hdr = process.ReadMemory(tsmat_ptr, 16, lldb.SBError())
                        if tsmat_hdr and len(tsmat_hdr) == 16:
                            next_ptr, data_ptr = struct.unpack("<QQ", tsmat_hdr)
                            capture["stata_state"]["tsmat_next"] = next_ptr
                            capture["stata_state"]["tsmat_data"] = data_ptr
                            if data_ptr and data_ptr > 0x100000:
                                str_ptr = process.ReadUnsignedFromMemory(data_ptr, 8, lldb.SBError())
                                capture["stata_state"]["tsmat_str_ptr"] = str_ptr
                                if str_ptr and str_ptr > 0x100000:
                                    str_len = process.ReadUnsignedFromMemory(str_ptr, 4, lldb.SBError())
                                    capture["stata_state"]["tsmat_str_len"] = str_len
                                    if 0 < str_len < 10000:
                                        s = process.ReadMemory(str_ptr + 4, min(str_len, 200), lldb.SBError())
                                        if s:
                                            capture["stata_state"]["tsmat_str"] = s.decode("utf-8", errors="replace")
                    except:
                        pass
        except Exception as e:
            _log(f"Stata state error: {e}")

    # Read ARM64 stack near SP
    try:
        arm64_sp = regs.get("sp", 0)
        if arm64_sp:
            sp_bytes = process.ReadMemory(arm64_sp, 64, lldb.SBError())
            if sp_bytes:
                capture["memory"]["arm64_sp_hex"] = sp_bytes.hex()
    except:
        pass

    CAPTURES.append(capture)

    summary = f"[{fn_name:20s}] w0={regs.get('w0',0)} x0={hex(regs.get('x0',0))} sp={hex(capture['stata_state'].get('internal_sp',0))} err={capture['stata_state'].get('err_code')} val={capture['stata_state'].get('tsmat_str','')[:40]}"
    _log(summary)

    return False  # continue execution


def _log(msg):
    try:
        print(f"[capture] {msg}", flush=True)
    except:
        pass


# ====== lldb command functions ======

def report_hit(debugger, command, result, internal_dict):
    """Called from lldb 'script report_hit()' breakpoint command."""
    # lldb sets frame, bp_loc, etc. as globals when breakpoint commands fire
    # But in 'script' command context, they're not available.
    # We need to use the global state lldb provides.
    target = debugger.GetSelectedTarget()
    if not target:
        result.PutCString("ERROR: no target")
        return
    process = target.GetProcess()
    if not process:
        result.PutCString("ERROR: no process")
        return
    thread = process.GetSelectedThread()
    if not thread:
        result.PutCString("ERROR: no thread")
        return
    frame = thread.GetFrameAtIndex(0)
    if not frame:
        result.PutCString("ERROR: no frame")
        return

    # Get breakpoint info
    stop_reason = thread.GetStopReason()
    if stop_reason == lldb.eStopReasonBreakpoint:
        bp_id = thread.GetStopReasonDataAtIndex(0)
        bp_loc_id = thread.GetStopReasonDataAtIndex(1)
        loc = target.GetBreakpointAtIndex(bp_id).GetLocationAtIndex(bp_loc_id)
    else:
        loc = None

    capture_at_breakpoint(frame, loc, None, {'debugger': debugger})
    result.PutCString("captured")


def show_hits(debugger, command, result, internal_dict):
    """Show captured data."""
    result.PutCString(f"Captures: {len(CAPTURES)}")
    for idx, c in enumerate(CAPTURES):
        ss = c.get("stata_state", {})
        regs = c.get("registers", {})
        vals = c.get("memory", {}).get("internal_stack_vals", [])
        line = f"  [{idx}] {c['function']:20s} w0={regs.get('w0')} sp={hex(ss.get('internal_sp',0))} vals={vals[:6]} err={ss.get('err_code')}"
        result.PutCString(line)


def write_report(debugger, command, result, internal_dict):
    """Write captures to JSON file."""
    with open(OUTPUT_FILE, "w") as f:
        json.dump({"captures": CAPTURES}, f, indent=2, default=str)
    result.PutCString(f"Wrote {len(CAPTURES)} captures to {OUTPUT_FILE}")


def setup(debugger, command, result, internal_dict):
    """Initial setup: load manifest and register commands."""
    load_manifest()
    debugger.HandleCommand("command script add -f lldb_report.report_hit report_hit")
    debugger.HandleCommand("command script add -f lldb_report.show_hits show_hits")
    debugger.HandleCommand("command script add -f lldb_report.write_report write_report")
    result.PutCString("Capture commands ready")


if __name__ == "__main__":
    print("Use: lldb -b -o 'script exec(open(\"scripts/lldb_report.py\").read())' ...")
