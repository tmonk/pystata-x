#!/usr/bin/env python3
"""
Phase 1: lldb state capture harness for reverse-engineering _bist_*/_bi_st_* functions.

Usage:
    lldb -b -o "command script import scripts/lldb_capture.py" \\
         -o "capture_init" \\
         -o "process launch" \\
         -o "capture_report" \\
         -o "continue" \\
         /path/to/python3 -- /path/to/script.py

Strategy:
    1. Set a single breakpoint on exported _StataSO_Main (works by name).
    2. On first hit (during Python's initialize()), discover _BASE and set
       additional function breakpoints at their load addresses.
    3. On subsequent hits, capture registers, internal stack, and state.
    4. After the function returns, capture post-state if possible.
"""

import lldb
import json
import os
import struct
import uuid

DEBUG = os.environ.get("LLDB_CAPTURE_DEBUG", "0") == "1"
OUTPUT_FILE = "/tmp/lldb_capture.json"

MANIFEST = None
CAPTURES = []
BP_FUNCS = {}        # bp_id -> func_name
TARGET_FUNCS = []    # list of function names to capture

STACK_PTR_OFFSET = 0x39b7000 + 0x108
ERR_CODE_OFFSET = 0x39b7000 + 0x11c

SETUP_DONE = False


def log(msg):
    if DEBUG:
        print(f"[lldb_capture] {msg}", flush=True)


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
            log(f"Loaded manifest ({len(MANIFEST['symbols'])} symbols)")
            return MANIFEST
    raise RuntimeError("Cannot find manifest.json")


def is_libstata_module(mod):
    """Check if a module is libstata."""
    fname = mod.GetFileSpec().GetFilename()
    return fname and "libstata" in fname


def find_libstata_base(target):
    """Find libstata's base load address from loaded modules."""
    for i in range(target.GetNumModules()):
        mod = target.GetModuleAtIndex(i)
        if is_libstata_module(mod):
            # First section = __TEXT, its load address = module base
            sec = mod.GetSectionAtIndex(0)
            if sec:
                return sec.GetLoadAddress(target)
    return 0


def resolve_function_address(target, fn_name):
    """Resolve the load address of a function from manifest offset."""
    manifest = load_manifest()
    if fn_name not in manifest["symbols"]:
        return 0
    offset = manifest["symbols"][fn_name]
    base = find_libstata_base(target)
    if base:
        return base + offset
    return 0


def capture_state(frame):
    """Capture function state at breakpoint hit."""
    thread = frame.GetThread()
    process = thread.GetProcess()
    target = process.GetTarget()
    debugger = target.GetDebugger()

    bp_id = frame.GetBreakpoint().GetID()
    func_name = BP_FUNCS.get(bp_id, "unknown")

    # Registers
    regs = {}
    for name in ["x0", "x1", "x2", "x3", "x4", "x5", "x6", "x7", "x8",
                  "w0", "sp", "pc", "lr", "fp", "cpsr"]:
        try:
            r = frame.FindRegister(name)
            if r:
                regs[name] = r.GetValueAsUnsigned()
        except:
            pass

    pc = regs.get("pc", 0)
    base_addr = find_libstata_base(target)
    manifest = load_manifest()
    fn_offset = manifest["symbols"].get(func_name, 0)

    capture = {
        "id": str(uuid.uuid4())[:8],
        "function": func_name,
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
            internal_sp = process.ReadUnsignedFromMemory(
                internal_sp_addr, 8, lldb.SBError())
            capture["stata_state"]["internal_sp_addr"] = internal_sp_addr
            capture["stata_state"]["internal_sp"] = internal_sp

            # Read 128 bytes of internal stack context (both sides of SP)
            stack_read_addr = internal_sp - 48 if internal_sp > 48 else internal_sp
            stack_bytes = process.ReadMemory(
                stack_read_addr, 128, lldb.SBError())
            if stack_bytes and len(stack_bytes) > 0:
                vals = []
                for i in range(0, min(len(stack_bytes), 128), 8):
                    chunk = stack_bytes[i:i+8]
                    if len(chunk) == 8:
                        val = struct.unpack("<Q", chunk)[0]
                        vals.append(val)
                capture["memory"]["internal_stack"] = {
                    "addr": stack_read_addr,
                    "bytes_hex": stack_bytes.hex(),
                }
                capture["memory"]["internal_stack_vals"] = [hex(v) for v in vals]

            # Read error code
            err_val = process.ReadUnsignedFromMemory(err_addr, 4, lldb.SBError())
            capture["stata_state"]["err_code"] = err_val
            capture["stata_state"]["err_code_addr"] = err_addr

            # Read tsmat at current SP
            tsmat_ptr = process.ReadUnsignedFromMemory(internal_sp, 8, lldb.SBError())
            capture["stata_state"]["tsmat_at_sp"] = tsmat_ptr
            if tsmat_ptr:
                # Read tsmat header: [next_ptr, data_ptr] (16 bytes)
                tsmat_hdr = process.ReadMemory(tsmat_ptr, 16, lldb.SBError())
                if tsmat_hdr and len(tsmat_hdr) == 16:
                    next_ptr, data_ptr = struct.unpack("<QQ", tsmat_hdr)
                    capture["stata_state"]["tsmat_next"] = next_ptr
                    capture["stata_state"]["tsmat_data"] = data_ptr
                    if data_ptr:
                        # Try to read string or double from tsmat data
                        data_val = process.ReadUnsignedFromMemory(
                            data_ptr, 8, lldb.SBError())
                        capture["stata_state"]["tsmat_raw_double"] = data_val
                        # Try reading as str pointer chain
                        str_ptr = process.ReadUnsignedFromMemory(
                            data_ptr, 8, lldb.SBError())
                        capture["stata_state"]["tsmat_str_ptr"] = str_ptr
                        if str_ptr and str_ptr > 0x100000:
                            str_len = process.ReadUnsignedFromMemory(
                                str_ptr, 4, lldb.SBError())
                            capture["stata_state"]["tsmat_str_len"] = str_len
                            if str_len < 10000 and str_len > 0:
                                try:
                                    s = process.ReadMemory(str_ptr + 4, min(str_len, 200),
                                                           lldb.SBError())
                                    if s:
                                        capture["stata_state"]["tsmat_str"] = s.decode("utf-8", errors="replace")
                                except:
                                    pass

        except Exception as e:
            log(f"Error reading Stata state: {e}")

    # Read ARM64 process stack near SP
    try:
        arm64_sp = regs.get("sp", 0)
        if arm64_sp:
            sp_bytes = process.ReadMemory(arm64_sp, 64, lldb.SBError())
            if sp_bytes:
                capture["memory"]["arm64_sp"] = {
                    "addr": arm64_sp,
                    "hex": sp_bytes.hex(),
                }
    except:
        pass

    CAPTURES.append(capture)
    log(f"=== Captured {func_name} (pc={hex(pc)}, base={hex(base_addr)}) ===")
    log(f"  w0={regs.get('w0', '?')}  x0={hex(regs.get('x0', 0))}")
    log(f"  internal SP={hex(capture['stata_state'].get('internal_sp', 0))}")
    log(f"  tsmat_at_sp={hex(capture['stata_state'].get('tsmat_at_sp', 0))}")
    vals = capture.get("memory", {}).get("internal_stack_vals", [])
    if vals:
        log(f"  stack vals: {vals}")
    log(f"  err_code={capture['stata_state'].get('err_code')}")

    return False  # don't stop, continue execution


def _callback_setup(frame, loc, user_data):
    """First callback — discover base and install target breakpoints."""
    global SETUP_DONE
    if SETUP_DONE:
        return capture_callback(frame, loc, user_data)

    thread = frame.GetThread()
    process = thread.GetProcess()
    target = process.GetTarget()

    base_addr = find_libstata_base(target)
    log(f"Libstata base address: {hex(base_addr)}")
    manifest = load_manifest()

    if not base_addr:
        log("ERROR: Cannot determine libstata base!")
        return False

    # Install breakpoints on target functions
    count = 0
    for fn_name in TARGET_FUNCS:
        if fn_name not in manifest["symbols"]:
            continue
        offset = manifest["symbols"][fn_name]
        addr = base_addr + offset
        bp = target.BreakpointCreateByAddress(addr)
        bp.SetBreakpointName(fn_name)
        bp.SetCallback(capture_callback)
        BP_FUNCS[bp.GetID()] = fn_name
        count += 1
        log(f"  BP set: {fn_name} @ {hex(addr)}")

    log(f"Installed {count} target breakpoints")

    # Remove the setup breakpoint (the one we're currently stopped at)
    current_bp = frame.GetBreakpoint()
    target.BreakpointDelete(current_bp.GetID())

    SETUP_DONE = True
    log("Setup complete — continuing")

    # For the _StataSO_Main hit, also capture state
    return capture_callback(bp_loc, extra_args, exe_ctx)


def capture_callback(bp_loc, extra_args, exe_ctx):
    """Capture state at any breakpoint hit (after setup)."""
    return capture_state(exe_ctx)


def __lldb_init_module(debugger, internal_dict):
    """Called when script is imported into lldb."""
    log("lldb_capture.py loaded")
    debugger.HandleCommand(
        "command script add -f lldb_capture.capture_init capture_init")
    debugger.HandleCommand(
        "command script add -f lldb_capture.capture_report capture_report")
    debugger.HandleCommand(
        "command script add -f lldb_capture.set_targets set_targets")
    debugger.HandleCommand(
        "command script add -f lldb_capture.show_captures show_captures")
    log("Commands registered: capture_init, capture_report, set_targets, show_captures")


def capture_init(debugger, command, result, internal_dict):
    """Initialize: set breakpoint on _StataSO_Main to discover base, then install targets."""
    global TARGET_FUNCS, SETUP_DONE
    SETUP_DONE = False

    target = debugger.GetSelectedTarget()
    if not target:
        result.PutError("No target selected")
        return

    # Default target functions (override via set_targets before capture_init)
    if not TARGET_FUNCS:
        TARGET_FUNCS = [
            "_bi_st_strlpart",
            "_bist_sdata",
            "_bist_data",
        ]

    # Set a breakpoint on the exported _StataSO_Main function
    bp_main = target.BreakpointCreateByName("_StataSO_Main")
    bp_main.SetBreakpointName("_StataSO_Main")
    bp_main.SetCallback(_callback_setup)
    log("Set setup breakpoint on _StataSO_Main")

    result.PutOK(f"Initialized with {len(TARGET_FUNCS)} target functions")


def set_targets(debugger, command, result, internal_dict):
    """Set target functions for capture. Pass as comma-separated names."""
    global TARGET_FUNCS
    names = [n.strip() for n in command.split(",") if n.strip()]
    if names:
        TARGET_FUNCS = names
    result.PutOK(f"Targets: {TARGET_FUNCS}")


def capture_report(debugger, command, result, internal_dict):
    """Write all captures to /tmp/lldb_capture.json."""
    path = OUTPUT_FILE
    with open(path, "w") as f:
        json.dump({
            "captures": CAPTURES,
            "meta": {
                "num_captures": len(CAPTURES),
                "target_funcs": TARGET_FUNCS,
            }
        }, f, indent=2, default=str)
    result.PutOK(f"Wrote {len(CAPTURES)} captures to {path}")


def show_captures(debugger, command, result, internal_dict):
    """Print captured state summaries."""
    for cap in CAPTURES:
        r = cap.get("registers", {})
        ss = cap.get("stata_state", {})
        mem = cap.get("memory", {})
        base = hex(cap.get("base_addr", 0))
        isp = ss.get("internal_sp", 0)
        tsmat = ss.get("tsmat_at_sp", 0)
        tw = ss.get("tsmat_str", "") or str(ss.get("tsmat_raw_double", ""))
        vals = mem.get("internal_stack_vals", [])
        result.AppendMessage(
            f"  [{cap['id']}] {cap['function']:20s} "
            f"w0={r.get('w0',0):3d} "
            f"x0={hex(r.get('x0',0)):18s} "
            f"SP={hex(isp):18s} "
            f"tsmat={hex(tsmat):18s} "
            f"val={tw[:40]:40s} "
            f"err={ss.get('err_code')}"
        )
