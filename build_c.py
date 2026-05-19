#!/usr/bin/env python3
"""
Cross-platform build helper for libstata_fast.

Builds the C shared library using CMake and copies the output into
the Python package directory (src/pystata_x/) so it's included in
the wheel.

Usage:
    python3 build_c.py                     # debug build
    python3 build_c.py --release           # release (-O2) build
    python3 build_c.py --clean             # remove build artifacts
    python3 build_c.py --install-package   # copy .dylib/.so/.dll into package

Requires: CMake >= 3.20, C99 compiler
"""

import argparse
import platform
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src" / "stata-fast"
BUILD_DIR = SRC_DIR / "build"
PKG_DIR = REPO_ROOT / "src" / "pystata_x"


def get_lib_name() -> str:
    system = platform.system()
    if system == "Darwin":
        return "libstata_fast.dylib"
    elif system == "Windows":
        return "stata_fast.dll"
    else:
        return "libstata_fast.so"


def cmake_configure(build_type: str) -> None:
    """Run CMake configure."""
    cmd = [
        "cmake",
        "-S", str(SRC_DIR),
        "-B", str(BUILD_DIR),
        f"-DCMAKE_BUILD_TYPE={build_type}",
        f"-DSTATA_PATH=/Applications/StataNow",   # macOS default
        f"-DSTATA_EDITION=se",
    ]
    print(f"[build_c] cmake configure: {' '.join(cmd)}")
    subprocess.check_call(cmd)


def cmake_build() -> None:
    """Run CMake build."""
    cmd = ["cmake", "--build", str(BUILD_DIR), "--verbose"]
    print(f"[build_c] cmake build: {' '.join(cmd)}")
    subprocess.check_call(cmd)


def clean() -> None:
    """Remove build artifacts."""
    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)
        print(f"[build_c] removed {BUILD_DIR}")
    for lib_file in PKG_DIR.glob("libstata_fast.*"):
        lib_file.unlink()
        print(f"[build_c] removed {lib_file}")
    for lib_file in PKG_DIR.glob("stata_fast.dll"):
        lib_file.unlink()
        print(f"[build_c] removed {lib_file}")


def install_into_package() -> None:
    """Copy compiled library into the Python package directory."""
    lib_name = get_lib_name()
    src = BUILD_DIR / lib_name
    if not src.exists():
        # Try Release/ subdirectory (Windows MSVC)
        src = BUILD_DIR / "Release" / lib_name
    if not src.exists():
        print(f"[build_c] ERROR: compiled library not found at {BUILD_DIR / lib_name}")
        print("  Run 'python3 build_c.py' first to build.")
        sys.exit(1)

    dst = PKG_DIR / lib_name
    shutil.copy2(str(src), str(dst))
    print(f"[build_c] installed {src} -> {dst}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build libstata_fast C library")
    parser.add_argument("--release", action="store_true", help="Build with -O2 (Release)")
    parser.add_argument("--clean", action="store_true", help="Remove build artifacts")
    parser.add_argument(
        "--install-package", action="store_true",
        help="Only copy compiled library into Python package (skip build)"
    )
    args = parser.parse_args()

    if args.clean:
        clean()
        return

    if args.install_package:
        install_into_package()
        return

    build_type = "Release" if args.release else "Debug"
    cmake_configure(build_type)
    cmake_build()
    install_into_package()
    print(f"[build_c] done — {get_lib_name()} built and installed into package")


if __name__ == "__main__":
    main()
