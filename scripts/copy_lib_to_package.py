#!/usr/bin/env python3
"""
Copy the compiled libstata_fast C library into the Python package directory.

Intended to be run by cibuildwheel (via before-build).
"""
import shutil
import sys
import platform
from pathlib import Path


def main() -> None:
    build_dir = Path("src/stata-fast/build")
    pkg_dir = Path("src/pystata_x")

    system = platform.system()
    if system == "Darwin":
        src = build_dir / "libstata_fast.dylib"
    elif system == "Windows":
        src = build_dir / "stata_fast.dll"
        if not src.exists():
            src = build_dir / "Release" / "stata_fast.dll"
    else:
        src = build_dir / "libstata_fast.so"

    if src.exists():
        dst = pkg_dir / src.name
        shutil.copy2(str(src), str(dst))
        print(f"Copied {src} -> {dst}", flush=True)
    else:
        print(f"WARNING: {src} not found, building without bundled library", flush=True)
        sys.exit(0)  # Non-fatal — library can be found at runtime


if __name__ == "__main__":
    main()
