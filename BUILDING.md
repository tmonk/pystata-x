# Building pystata-x

pystata_x combines a Python package with a C shared library (`libstata_fast`
/ `stata_fast.dll`) that wraps Stata's engine API for low-latency command
execution.

## Prerequisites

- [StataNow](https://www.stata.com/statanow/) or Stata 18+ installed
- Python 3.10+
- C99 compiler (varies by platform)
- CMake 3.20+ (recommended) **or** `make` (macOS/Linux only)

## Known Platform Configurations

| Platform | Host arch | Stata arch | C ext arch | Status |
|----------|-----------|------------|------------|--------|
| macOS | ARM64 (M1–M4) | ARM64 | ARM64 | ✅ Full support |
| Linux | x86_64 | x86_64 | x86_64 | 🟢 Compile + unit tests; Stata tests untested |
| Linux | **ARM64** (with RosettaLinux) | x86_64 | x86_64 | 🟡 See § Linux ARM64 |
| Windows | x86_64 | x86_64 | x86_64 | 🟢 Compile + unit tests; Stata tests untested |
| Windows | **ARM64** (Snapdragon X) | x86_64 (emu) | x86_64 | 🟡 See § Windows ARM64 |

## Platform Toolchain

### macOS (ARM64 / x86_64)

| Tool | Minimum | Install |
|------|---------|---------|
| C compiler | clang (Xcode CLT) | `xcode-select --install` |
| CMake | 3.20 | `brew install cmake` |
| Python | 3.10 | `brew install python` or `uv python install` |
| capstone | 5.0.0 | `pip install capstone` |
| Stata | StataNow / Stata 18+ | `/Applications/StataNow/` |

```bash
# Quick build
cd src/stata-fast
make          # → libstata_fast.dylib
make test     # build + run C tests

# With CMake
cmake -S . -B build -DSTATA_PATH="/Applications/StataNow" -DSTATA_EDITION=se
cmake --build build
```

### Linux (x86_64 native)

| Tool | Minimum | Install |
|------|---------|---------|
| C compiler | gcc or clang | `apt install gcc` / `yum install gcc` |
| CMake | 3.20 | `apt install cmake` |
| Python | 3.10 | `apt install python3 python3-pip python3-venv` |
| capstone | 5.0.0 | `pip install capstone` |
| Stata | StataNow / Stata 18+ | `/usr/local/statanow/` or `/usr/local/stata19/` |

```bash
cmake -S src/stata-fast -B build \
    -DSTATA_PATH="/usr/local/stata19" -DSTATA_EDITION=se
cmake --build build
```

### Linux (ARM64 → x86_64 target) ⚠️

On ARM64 Linux (e.g. Ampere Altra, Raspberry Pi 5 with Box64/RosettaLinux),
Stata may be an x86_64 binary running under emulation. Both the C extension
and Stata-integration tests require **x86_64** tooling.

| Tool | Minimum | Install |
|------|---------|---------|
| C compiler | x86_64 cross-GCC | `sudo apt install gcc-x86-64-linux-gnu` |
| CMake | 3.20 | `sudo apt install cmake` |
| Python (native) | 3.10 | `sudo apt install python3 python3-pip python3-venv` |
| Python (x86_64) | 3.12+ | Standalone build (see below) |
| capstone | 5.0.0 | `pip install capstone` (native ARM64 wheel available) |
| Stata | StataNow / Stata 18+ (x86_64) | `/usr/local/stata19/` |

**x86_64 Python standalone install:**
```bash
cd /opt
sudo curl -L 'https://github.com/astral-sh/python-build-standalone/releases/download/20260510/cpython-3.12.13%2B20260510-x86_64-unknown-linux-gnu-install_only.tar.gz' | sudo tar -xz
# Gives /opt/python/bin/python3 — an x86_64 binary that runs under RosettaLinux
```

**C extension build:**
```bash
cmake -S src/stata-fast -B src/stata-fast/build \
    -DCMAKE_C_COMPILER=x86_64-linux-gnu-gcc \
    -DSTATA_PATH=/usr/local/stata19 -DSTATA_EDITION=se
cmake --build src/stata-fast/build
```

**Running Stata integration tests** (requires x86_64 Python):
```bash
export LD_LIBRARY_PATH=/usr/local/stata19:$LD_LIBRARY_PATH
/opt/python/bin/python3 -m pytest tests/
```

### Windows (x86_64 native)

| Tool | Minimum | Install |
|------|---------|---------|
| C compiler | MSVC or MinGW-w64 | `winget install Microsoft.VisualStudio.2022.BuildTools`\* or `scoop install mingw` |
| CMake | 3.20 | `winget install Kitware.CMake` |
| Python | 3.10 (64-bit) | `scoop install python` or python.org |
| capstone | 5.0.0 | `pip install capstone` (win_amd64 wheel available) |
| Stata | StataNow / Stata 18+ | `C:\Program Files\StataNow19\` |

> \* When using MSVC, open a **Developer Command Prompt** (or run
> `vcvarsall.bat x64`) before running CMake so `cl.exe` and `nmake` are in PATH.

```cmd
cmake -S src/stata-fast -B build -DSTATA_PATH="C:\Program Files\StataNow19" -DSTATA_EDITION=se
cmake --build build
```

**Note**: StataNow on Windows uses `se-64.dll` (not `StataSE-64.dll`). The
toolchain auto-detects this.

### Windows (ARM64 → x86_64 target) ⚠️

On ARM64 Windows (e.g. Snapdragon X Elite, Surface Pro X), Stata is an x86_64
binary running under emulation. Both the C extension and Stata-integration
tests require **x86_64** tooling.

| Tool | Minimum | Install |
|------|---------|---------|
| C compiler | LLVM MinGW (x86_64 cross) | `winget install MartinStorsjo.LLVM-MinGW.UCRT` |
| CMake | 3.20 | `winget install Kitware.CMake` |
| Python (ARM64) | 3.10 | python.org — **unit tests only** |
| Python (x86_64) | 3.10 | Standalone build (see below) |
| capstone | **≥ 6.0.0a5** | `pip install capstone` — 5.x lacks win_arm64 binary wheels |
| Stata | StataNow / Stata 18+ (x86_64) | `C:\Program Files\StataNow19\` |

**x86_64 Python standalone install:**
```cmd
REM Download from GitHub releases
curl -sL -o cpython-x64.tar.gz "https://github.com/astral-sh/python-build-standalone/releases/download/20260510/cpython-3.14.5%%2B20260510-x86_64-pc-windows-msvc-install_only.tar.gz"
REM Extract with Python
python -c "import tarfile; tarfile.open('cpython-x64.tar.gz').extractall('python-x64')"
REM → python-x64\python\python.exe
```

**C extension build (cross-compile to x86_64):**
```cmd
set PATH=%USERPROFILE%\AppData\Local\Microsoft\WinGet\Packages\MartinStorsjo.LLVM-MinGW.UCRT_Microsoft.Winget.Source_8wekyb3d8bbwe\llvm-mingw-20260505-ucrt-aarch64\bin;%PATH%
cmake -G "MinGW Makefiles" -DCMAKE_C_COMPILER=x86_64-w64-mingw32-gcc ^
    -DCMAKE_MAKE_PROGRAM=mingw32-make ^
    -DSTATA_PATH="C:\Program Files\StataNow19" -DSTATA_EDITION=se ^
    -S src/stata-fast -B src/stata-fast/build
cmake --build src/stata-fast/build
```

**⚠️ Architecture mismatch**: ARM64 Python cannot load Stata's x86_64 DLL
(`[WinError 193] %1 is not a valid Win32 application`). Options for running
Stata integration tests:

1. **Use x86_64 Python** — the standalone build above runs under emulation
   and can load Stata's DLL natively.
2. **Use Stata's embedded Python** — run tests inside Stata via `python:`
   blocks (Stata launches its own x86_64 Python interpreter).
3. **Unit tests only** — 126 tests in `tests/unit/` mock `ctypes.cast` and
   pass with ARM64 Python (no Stata DLL needed).

## `_bist_*` Calling Convention (All Platforms)

The `_bist_*` and `_pushint`/`_pushdbl`/`_pushstr` functions are **internal
Stata functions** that use Stata's proprietary calling convention on ALL
platforms — they do NOT use the standard platform ABI (SysV, Microsoft x64,
or AAPCS64).

- **ARM64** (fully analysed): Push+stack convention —
  `_pushint`/`_pushdbl`/`_pushstr` write to Stata's internal expression stack,
  the `_bist_*` function reads from it and pushes its result, and the caller
  reads the result from the stack then restores the stack pointer. The stack
  pointer location (`stack_ptr_off`) and error-address offset
  (`err_addr_off`) are discovered dynamically via Capstone disassembly of
  `_pushdbl` at manifest-generation time.

- **x86_64 / Windows** (not yet analysed): The standard-ABI assumption (direct
  CFUNCTYPE calls) is **known to be incorrect** — calling `_bist_nobs` or
  `_pushint` via standard ABI on x86_64 Linux causes the process to hang.
  Full reverse engineering of the x86_64 internal convention is needed before
  the fast `_bist_*` path can be enabled on these platforms.

**Practical impact**: On x86_64 and Windows today, `StataSO_Execute` (the
public API) works perfectly for command execution. Data access via the
`_bist_*` fast path (used by `Data.getObsTotal()`, `Macro.getGlobal()`, etc.)
does not work. All exported `StataSO_*` functions use standard ABI and work
correctly.

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

# End-to-end tests (requires Stata, x86_64 arch matching)
pytest tests/e2e/ -v
```

## Benchmarks

### Linux (ARM64 + RosettaLinux, x86_64 Stata)
| Metric | Result |
|--------|--------|
| Cold init (StataSO_Main) | **44 ms** |
| Basic execution (StataSO_Execute) | **25 µs per call** |

### Windows (ARM64 + emulation, x86_64 Stata)
| Metric | Result |
|--------|--------|
| Cold init (StataSO_Main) | **6.4 ms** |
| Basic execution (StataSO_Execute) | **3.2 µs per call** |

## CI

GitHub Actions CI builds and tests on:
- macOS 14 (ARM64) — full Stata tests
- Ubuntu 22.04 (x86_64) — compile-check only (no Stata on CI)
- Windows 2022 (x86_64) — compile-check only (no Stata on CI)

See `.github/workflows/build-test.yml` for details.


## Docker development workflow (x86_64 Linux)

The project supports Linux x86_64 testing via Docker Desktop with Rosetta 2.
Stata Linux files are mounted from the host at container runtime.

### Quick reference

```bash
# Build the image (one-time)
docker build -f Dockerfile.amd64 -t pystata-x-linux .

# Create the persistent container
docker create --name pystata-x-persist \
  -v "$(pwd):/pystata-x" \
  -v "$(pwd)/stata19-linux:/usr/local/stata19" \
  pystata-x-linux \
  /pystata-x/docker-entrypoint.sh

# Start the container (always do this before testing)
docker start pystata-x-persist
sleep 2  # wait for entrypoint to reinstall packages

### Quick test commands

```bash
# Unit tests (115 tests, no Stata needed)
docker exec pystata-x-persist /pystata-x/docker-entrypoint.sh unit

# pystata-analyzer tests (10 unit + 13 integration)
docker exec pystata-x-persist /pystata-x/docker-entrypoint.sh framework

# E2e tests (71 tests, requires Stata)
docker exec pystata-x-persist /pystata-x/docker-entrypoint.sh e2e

# Everything
docker exec pystata-x-persist /pystata-x/docker-entrypoint.sh all
```

### Using the analyzer framework

```bash
# Full protocol report for any dispatch function
docker exec pystata-x-persist /pystata-x/docker-entrypoint.sh analyze _bist_data

# Catalog all 118+ dispatch functions
docker exec pystata-x-persist /pystata-x/docker-entrypoint.sh catalog
```

### Interactive shell

```bash
docker exec -it pystata-x-persist /pystata-x/docker-entrypoint.sh shell

# Inside the container:
python -c "
from pystata_analyzer import StataBinary
b = StataBinary('/usr/local/stata19/libstata-se.so')
b.analyze()
print(b.report())
"
```

If you don't want a persistent container:

```bash
docker run --rm --platform=linux/amd64 \
  -v "$(pwd):/pystata-x" \
  -v "$(pwd)/stata19-linux:/usr/local/stata19" \
  pystata-x-linux \
  /pystata-x/docker-entrypoint.sh test
```

### Debugging a crash

```bash
docker exec -it pystata-x-persist ./entrypoint.sh shell
# Inside container:
python -c "import pystata_x.sfi._engine as e; e.initialize(); ..."
```

### Rebuilding the image

```bash
git add -A && git commit -m "sync"
docker build -f Dockerfile.amd64 -t pystata-x-linux .
docker rm pystata-x-persist 2>/dev/null
docker create --name pystata-x-persist \
  -v "$(pwd):/pystata-x" \
  -v "$(pwd)/stata19-linux:/usr/local/stata19" \
  pystata-x-linux \
  /pystata-x/docker-entrypoint.sh
```
