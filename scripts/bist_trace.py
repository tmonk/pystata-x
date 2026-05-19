#!/usr/bin/env python3
"""
bist_trace.py — Trace _bist_* calling conventions using lldb attach-by-address.

Two-phase approach:
  1. Launch test script → initialises Stata, prints PID & _BASE, SIGSTOPs itself
  2. Attach lldb to the stopped process → set breakpoint at _BASE + manifest_addr
     → continue (SIGCONT) → breakpoint fires → capture → detach

Usage:
    python3 scripts/bist_trace.py _bist_data
    python3 scripts/bist_trace.py _bist_global
    python3 scripts/bist_trace.py --list
"""
from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
from pathlib import Path
from typing import Optional

# ── Paths ──────────────────────────────────────────────────────────
_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent
_MANIFEST_PATH = _PROJECT_ROOT / "src" / "pystata_x" / "sfi" / "manifest.json"
_TEST_SCRIPT = _HERE / "_minimal_stata_init.py"
_ATTACH_CAPTURE = _HERE / "bist_attach_capture.py"


def load_manifest() -> dict:
    if not _MANIFEST_PATH.exists():
        print(f"[ERROR] Manifest not at {_MANIFEST_PATH}", file=sys.stderr)
        sys.exit(1)
    with open(_MANIFEST_PATH) as f:
        return json.load(f)


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


def prepare_binary() -> str:
    """Copy binary to /tmp, add rpath for Frameworks, re-sign."""
    import shutil
    binary = "/Applications/StataNow/StataSE.app/Contents/MacOS/libstata-se.dylib"
    tmp_lib = Path("/tmp") / "libstata-traced.dylib"
    frameworks_dir = "/Applications/StataNow/StataSE.app/Contents/Frameworks"
    if not tmp_lib.exists():
        print(f"[bist] Copying {binary} -> {tmp_lib}...")
        shutil.copy2(binary, str(tmp_lib))
        tmp_lib.chmod(0o755)
        subprocess.run(
            ["install_name_tool", "-add_rpath", frameworks_dir, str(tmp_lib)],
            capture_output=True,
        )
        subprocess.run(["codesign", "-f", "-s", "-", str(tmp_lib)], capture_output=True)
        print(f"[bist] Ready")
    return str(tmp_lib)


def generate_lldb_commands(
    pid: int,
    func_name: str,
    runtime_addr: int,
    capture_py: str,
) -> str:
    """Generate a .lldb command file that attaches, sets breakpoint, continues."""
    lines = [
        f"# ---- bist_trace: {func_name} (attach to PID {pid}) ----",
        "",
        f"process attach --pid {pid}",
        "",
        f"# Import capture module (Python 3.9 compatible)",
        f"command script import \"{capture_py}\"",
        "",
        f"# Set address breakpoint",
        f"breakpoint set --address {runtime_addr}",
        "",
        f"# Register Python callback for breakpoint 1",
        f"breakpoint command add -s python 1 -o \"bist_attach_capture.capture_state\"",
        "",
        f"# Continue the process (sends SIGCONT after attach-stop)",
        f"continue",
        f"",
        f"# Brief pause for breakpoint to fire and callback to execute",
        f"script import time; time.sleep(0.3)",
        f"",
        f"# Detach (avoids killing the test process)",
        f"detach",
        f"quit",
    ]
    return "\n".join(lines)


def run_lldb_script(script_path, timeout=30):
    """Run lldb via PTY (interactive-like session for debug permissions)."""
    import pty, os as _os, select, time
    master_fd, slave_fd = pty.openpty()
    proc = subprocess.Popen(
        ["lldb", "-s", script_path],
        stdin=slave_fd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        close_fds=True,
    )
    _os.close(slave_fd)
    _os.set_blocking(master_fd, False)
    chunks = []
    start = time.time()
    while time.time() - start < timeout:
        r, _, _ = select.select([master_fd, proc.stdout], [], [], 0.1)
        for fd in r:
            if fd == master_fd:
                try:
                    d = _os.read(master_fd, 4096)
                    if d:
                        chunks.append(d.decode("utf-8", errors="replace"))
                except (BlockingIOError, OSError):
                    break
            elif fd == proc.stdout:
                d = proc.stdout.read(4096)
                if d:
                    chunks.append(d.decode("utf-8", errors="replace"))
        if proc.poll() is not None:
            try:
                while True:
                    d = _os.read(master_fd, 4096)
                    if not d:
                        break
                    chunks.append(d.decode("utf-8", errors="replace"))
            except (BlockingIOError, OSError):
                pass
            break
    _os.close(master_fd)
    proc.wait(5)
    stdout = "".join(chunks)
    stderr = proc.stderr.read() if proc.stderr else ""
    return (proc.returncode or 0), stdout, stderr


def parse_traces(output: str) -> list[dict]:
    """Extract BIST TRACE blocks from lldb output."""
    traces = []
    current = None
    for line in output.split("\n"):
        if "BIST TRACE:" in line:
            if current:
                traces.append(current)
            func = line.split("BIST TRACE:")[1].strip()
            current = {"function": func, "caller": "",
                       "registers": {}, "floats": {}, "stack": [],
                       "stata_value": None}
        elif current is not None:
            m = re.match(r"\s+(\w+)\s+=\s+(0x[0-9a-fA-F]+|\S+)", line.strip())
            if m:
                name, val = m.group(1), m.group(2)
                if name.startswith("d"):
                    current["floats"][name] = val
                elif name in ("x0", "x1", "x2", "x3", "x4", "x5", "x6", "x7",
                              "x8", "x9", "x10", "x28", "sp", "lr", "pc", "fp"):
                    current["registers"][name] = val
            elif "Caller:" in line:
                current["caller"] = line.split("Caller:")[1].strip()
            elif r"\*(double\*)data" in line or "result =" in line:
                m = re.search(r"= ([\d.]+)", line)
                if m:
                    current["stata_value"] = float(m.group(1))
    if current:
        traces.append(current)
    return traces


def main():
    parser = argparse.ArgumentParser(description="bist_trace.py — _bist_* tracer")
    parser.add_argument("function", nargs="?", help="Function to trace")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--pattern", default="_bist_")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--verbose", "-v", action="store_true")
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
        print("  python3 scripts/bist_trace.py _bist_data")
        print("  python3 scripts/bist_trace.py _bist_global")
        print("  python3 scripts/bist_trace.py --list")
        return

    manifest = load_manifest()
    func_addr = find_symbol(manifest, args.function)
    if func_addr is None:
        print(f"[ERROR] '{args.function}' not found in manifest")
        for k in sorted(manifest.get("symbols", {})):
            if args.function in k:
                print(f"  Did you mean: {k}")
        sys.exit(1)

    func_name = args.function

    # Prepare binary
    prepare_binary()

    # Set up environment for test script
    env = os.environ.copy()
    env["STATA_LIB_PATH"] = "/tmp/libstata-traced.dylib"
    env["PYTHONPATH"] = f"{_PROJECT_ROOT / 'src'}:{_HERE}"

    print(f"[bist] Function: {func_name} (manifest addr: {func_addr})")
    print(f"[bist] Launching test script...")

    # Phase 1: Launch test script and wait for it to SIGSTOP itself
    proc = subprocess.Popen(
        [sys.executable, str(_TEST_SCRIPT), func_name],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        text=True,
        bufsize=1,
    )

    # Parse output to get PID, _BASE, and READY signal
    pid = None
    base = None
    ready = False
    test_output = []

    start = time.time()
    while time.time() - start < 15:
        line = proc.stdout.readline() if proc.stdout else ""
        if not line:
            time.sleep(0.05)
            # Check if process exited (shouldn't — should be stopped)
            poll = proc.poll()
            if poll is not None:
                print(f"[bist] Test process exited early with code {poll}")
                break
            continue

        line = line.strip()
        test_output.append(line)
        print(line)

        if line.startswith("[test] PID:"):
            pid = int(line.split("PID:")[1].strip())
        elif line.startswith("[test] _BASE:"):
            base_str = line.split("_BASE:")[1].strip()
            base = int(base_str, 16)
        elif line == "[test] READY_FOR_LLDB":
            ready = True
            break

    if pid is None or base is None or not ready:
        print(f"[ERROR] Test script did not provide required info")
        print(f"  pid={pid}, base=0x{base:x if base else 0}, ready={ready}")
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        sys.exit(1)

    runtime_addr = base + func_addr
    print(f"\n[bist] PID={pid}, _BASE=0x{base:x}, runtime addr=0x{runtime_addr:x}")

    # Phase 2: Generate .lldb script and run lldb
    lldb_content = generate_lldb_commands(
        pid=pid,
        func_name=func_name,
        runtime_addr=runtime_addr,
        capture_py=str(_ATTACH_CAPTURE),
    )

    if args.verbose:
        print(f"\n[bist] lldb commands:")
        for line in lldb_content.split("\n"):
            print(f"  {line}")

    # Write temp .lldb file
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".lldb", delete=False, dir="/tmp",
    ) as f:
        f.write(lldb_content)
        lldb_path = f.name

    try:
        print(f"\n[bist] Attaching lldb...")
        rc, stdout, stderr = run_lldb_script(lldb_path, timeout=args.timeout)

        # Print lldb output
        if stdout:
            print(f"\n[bist] lldb stdout ({len(stdout)} chars):")
            # Show lines containing key terms or last 30 lines
            keywords = ["bist", "trace", "breakpoint", "error", "libstata",
                        "x0", "caller", "stack"]
            shown = 0
            for line in stdout.split("\n"):
                if any(k in line.lower() for k in keywords):
                    print(f"  {line}")
                    shown += 1
            if shown == 0:
                # No keyword matches, show relevant sections
                lines = stdout.split("\n")
                for i, line in enumerate(lines):
                    if "BIST TRACE" in line or "Caller:" in line or "x0 " in line:
                        # Show 10 lines before and after
                        for l in lines[max(0, i-1):min(len(lines), i+15)]:
                            print(f"  {l}")
                        break

        if stderr:
            print(f"\n[bist] lldb stderr:")
            for line in stderr.split("\n")[-15:]:
                if line.strip():
                    print(f"  {line}")

        print(f"\n[bist] Exit code: {rc}")

    except subprocess.TimeoutExpired:
        print(f"[bist] TIMEOUT after {args.timeout}s")
    finally:
        # Clean up temp file
        os.unlink(lldb_path)
        # Kill test process
        try:
            proc.kill()
        except ProcessLookupError:
            pass


if __name__ == "__main__":
    main()
