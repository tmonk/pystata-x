#!/usr/bin/env python3
"""
_minimal_stata_init.py — Minimal Stata init that prints function address for lldb.

Usage:
  # Phase 1: Launch Python (this script), get PID and address
  python3 scripts/_minimal_stata_init.py _bist_data

  # Phase 2: In another terminal, attach lldb and set breakpoint:
  lldb -p $PID
  (lldb) breakpoint set -a 0xFUNC_ADDR
  (lldb) continue

  # Or use the bist_trace.py driver which does both phases automatically.
"""
from __future__ import annotations

import importlib
import os
import signal
import sys
import json
import time
from pathlib import Path
from typing import Optional

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

# Allow specifying the traced binary
_TMP_LIB = Path("/tmp") / "libstata-traced.dylib"
if _TMP_LIB.exists():
    os.environ["STATA_LIB_PATH"] = str(_TMP_LIB)


def main():
    func_name = sys.argv[1] if len(sys.argv) > 1 else "Data.getDouble"

    print(f"[test] PID: {os.getpid()}", flush=True)
    print(f"[test] Target: {func_name}", flush=True)

    # Read manifest for function address
    manifest_path = _PROJECT_ROOT / "src" / "pystata_x" / "sfi" / "manifest.json"
    with open(manifest_path) as f:
        manifest = json.load(f)

    # Check if it's a _bist_ function or a Python method path
    if func_name.startswith("_"):
        # It's a raw _bist_ function
        bist_addr = manifest.get("symbols", {}).get(func_name)
        print(f"[test] Manifest addr: {bist_addr}", flush=True)
    else:
        # It's a Python method — find the _bist_ function from _core
        bist_addr = None
        print(f"[test] Python method, will print _bist_ runtime addr later", flush=True)

    # Initialise Stata
    from pystata_x.sfi._engine import initialize, execute, _BASE
    initialize()
    print(f"[test] _BASE: 0x{_BASE:x}", flush=True)

    if bist_addr is not None:
        runtime_addr = _BASE + bist_addr
        print(f"[test] Runtime addr: 0x{runtime_addr:x}", flush=True)

    # Load dataset and call function
    from pystata_x.sfi._engine import execute
    execute("sysuse auto, clear")

    # Signal the driver that we're ready for lldb attachment
    print(f"[test] READY_FOR_LLDB", flush=True)
    # Send SIGSTOP to pause ourselves so lldb can attach
    os.kill(os.getpid(), signal.SIGSTOP)
    # After lldb continues us, call the function
    print(f"[test] Resumed by lldb, calling function...", flush=True)

    if func_name.startswith("_"):
        from pystata_x.sfi._engine import call_double
        result = call_double(func_name, 0, 0)
        print(f"[test] Result: {result!r}", flush=True)
    else:
        cls_name, meth_name = func_name.split(".")
        core = importlib.import_module("pystata_x.sfi._core")
        cls = getattr(core, cls_name)
        meth = getattr(cls, meth_name)
        if cls_name == "Data" and meth_name == "getDouble":
            result = meth(1, 0)
        elif cls_name == "Data" and meth_name == "getString":
            result = meth(0, 0)
        elif cls_name == "Data" and meth_name == "getVarCount":
            result = meth()
        elif cls_name == "Data" and meth_name == "getVarIndex":
            result = meth("make")
        elif cls_name == "Macro" and meth_name == "getGlobal":
            result = meth("e2e_test")
        elif cls_name == "Scalar" and meth_name == "getValue":
            result = meth("c(level)")
        elif cls_name == "ValueLabel" and meth_name == "exists":
            result = meth("origin")
        else:
            result = meth()
        print(f"[test] Result: {result!r}", flush=True)

    print(f"[test] Done.", flush=True)


if __name__ == "__main__":
    main()
