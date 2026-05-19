# Building pystata-x

pystata-x combines a Python package with a C shared library (`libstata_fast`)
that wraps Stata's engine API for low-latency command execution.

## Prerequisites

- [StataNow](https://www.stata.com/statanow/) or Stata 18+ installed
- Python 3.10+
- C99 compiler (varies by platform)
- CMake 3.20+ (recommended) **or** `make` (macOS/Linux only)

## Platform Toolchain

### macOS (ARM64 / x86_64)

| Tool | Minimum | Install |
|------|---------|---------|
| C compiler | clang (Xcode CLT) | `xcode-select --install` |
| CMake | 3.20 | `brew install cmake` |
| Python | 3.10 | `brew install python` or `uv python install` |
| capstone | 5.0.0 | `pip install capstone` |

```bash
# Quick build
cd src/stata-fast
make          # → libstata_fast.dylib
make test     # build + run C tests

# Or with CMake
cmake -S . -B build -DSTATA_PATH="/Applications/StataNow" -DSTATA_EDITION=se
cmake --build build
```

### Linux (x86_64 / ARM64)

| Tool | Minimum | Install |
|------|---------|---------|
| C compiler | gcc or clang | `apt install gcc` / `yum install gcc` |
| CMake | 3.20 | `apt install cmake` |
| Python | 3.10 | `apt install python3` |
| capstone | 5.0.0 | `pip install capstone` |

```bash
# CMake build
cmake -S src/stata-fast -B build \
    -DSTATA_PATH="/usr/local/statanow" -DSTATA_EDITION=se
cmake --build build
```

### Windows (x86_64 native)

| Tool | Minimum | Install |
|------|---------|---------|
| C compiler | MSVC or MinGW-w64 | `winget install Microsoft.VisualStudio.2022.BuildTools`\* or `scoop install mingw` |
| CMake | 3.20 | `winget install Kitware.CMake` |
| Python | 3.10 (64-bit) | `scoop install python` or python.org |
| capstone | 5.0.0 | `pip install capstone` |

> \* When using MSVC, open a **Developer Command Prompt** (or run
> `vcvarsall.bat x64`) before running CMake so `cl.exe` and `nmake` are in PATH.

```cmd
cmake -S src/stata-fast -B build -DSTATA_PATH="C:\Program Files\StataNow" -DSTATA_EDITION=se
cmake --build build
```

### Windows (ARM64 → x86_64 target) ⚠️

On ARM64 Windows (e.g. Snapdragon X Elite, Surface Pro X), Stata is an x86_64
binary running under emulation.  Both the C extension and Stata-integration tests
require **x86_64** tooling.

| Tool | Minimum | Install |
|------|---------|---------|
| C compiler | LLVM MinGW (x86_64 cross) | `winget install MartinStorsjo.LLVM-MinGW.UCRT` |
| CMake | 3.20 | `winget install Kitware.CMake` |
| Python (ARM64) | 3.10 | python.org — **unit tests only** |
| Python (x86_64) | 3.10 | For **Stata integration tests** (see note below) |
| capstone | **≥ 6.0.0a5** | `pip install capstone` — 5.x lacks win_arm64 binary wheels |
| Stata | StataNow / Stata 18+ (x86_64) | `C:\Program Files\StataNow19\` |

```cmd
REM Build the C extension with the cross-compiler
set PATH=%USERPROFILE%\AppData\Local\Microsoft\WinGet\Packages\MartinStorsjo.LLVM-MinGW.UCRT_Microsoft.Winget.Source_8wekyb3d8bbwe\llvm-mingw-20260505-ucrt-aarch64\bin;%PATH%
cmake -G "MinGW Makefiles" -DCMAKE_C_COMPILER=x86_64-w64-mingw32-gcc ^
    -DCMAKE_MAKE_PROGRAM=mingw32-make ^
    -DSTATA_PATH="C:\Program Files\StataNow19" -DSTATA_EDITION=se ^
    -S src/stata-fast -B src/stata-fast/build
cmake --build src/stata-fast/build
```

**⚠️ Architecture mismatch**: ARM64 Python cannot load Stata's x86_64 DLL
(`[WinError 193] %1 is not a valid Win32 application`).  Options for running
Stata integration tests:

1. **Use Stata's embedded Python** — run tests inside Stata via `python:`
   blocks (Stata launches its own x86_64 Python interpreter).
2. **Install a separate x86_64 Python** — e.g. download
   `python-3.14.5-amd64.exe` from python.org.  Runs under emulation and can
   load Stata's DLLs.
3. **Unit tests only** — 126 tests in `tests/unit/` mock `ctypes.cast` and
   pass with ARM64 Python (no Stata DLL needed).

## Python Package Install

```bash
# Editable install (development)
pip install -e ".[dev]"

# Or minimal install
pip install -e .
```

On ARM64 Windows, `capstone` pre-built wheels require ≥ 6.0.0a5 (the dependency
spec in `pyproject.toml` already reflects this).

## Running Tests

```bash
# Unit tests (no Stata needed)
pytest tests/unit/

# End-to-end tests (requires Stata)
pytest tests/e2e/ -v
```

## CI

GitHub Actions CI builds and tests on:
- macOS 14 (ARM64) — full Stata tests
- Ubuntu 22.04 (x86_64) — compile-check only (no Stata on CI)
- Windows 2022 (x86_64) — compile-check only (no Stata on CI)

See `.github/workflows/build-test.yml` for details.
