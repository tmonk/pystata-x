# pystata-x

Independent drop-in replacement for StataCorp's **pystata**. Provides a
fast `stata_setup` initialiser and command execution path that delivers
**~10–20,000×** speedup on short commands and **~11×** faster cold Stata
initialisation.

## Quick Start

```python
import sys
sys.path.insert(0, "path/to/pystata-x/src")

from pystata_x.stata_setup import config
config("/Applications/StataMP", "mp", splash=False)

# Use our fast execution:
from pystata_x._core import execute
output, rc = execute("display 1+1")
print(output)  # "2"
```

Or use the vendor-compatible API:

```python
from pystata_x._core import run
run("sysuse auto, clear")  # prints output, raises SystemError on error
```

## Why the polling thread is the bottleneck

The original `pystata.stata.run()` calls `RedirectOutput` from
`pystata.core.stout`, which creates a **`RepeatTimer` thread** that polls
Stata's output buffer every **15 ms**:

1. A background thread is created and started.
2. Every 15 ms it calls `StataSO_getOutput()` to fetch and display output.
3. After the command finishes a `"#return;0"` sentinel appears, the thread
   exits and is joined.

This design exists to support **Jupyter notebook interactivity** — users see
output streaming in as commands execute, like a live terminal. The polling
sleep (15 ms) plus thread lifecycle overhead adds **~40 ms of Python
overhead** on every `run()` call:

```
pystata.stata.run()  →  ~40 ms total
   ├─ thread create   ~1 ms
   ├─ 3× poll cycle   ~45 ms (3 × 15 ms)
   ├─ thread join     ~1 ms
   └─ work overhead   ~1 ms
```

For **headless / CLI / AI-agent** use cases (e.g., `stata-agent`), output is
captured programmatically after the command finishes — no streaming to a
terminal or notebook is needed. The polling thread is **pure overhead**.

`pystata-x` skips the thread entirely and calls `StataSO_Execute()` directly,
then drains the output buffer once after execution.

## Benchmark Results

Measured on macOS (StataSE, Apple Silicon M4) using
`benchmarks/run_benchmarks.py`.  Each test runs in a **fresh subprocess**
(Stata initialised once per test) with warm-up iterations before timing.
Times are the mean of multiple iterations measured via
`time.perf_counter()`.

### Command execution

| Test | Original pystata | pystata-x | Speedup |
|------|-----------------|-----------|---------|
| **Single command** (`display 1+1`) | ~40.6 ms | **~0.002 ms** | **~19,000×** |
| **Single command + echo** | ~40.7 ms | **~0.002 ms** | **~17,000×** |
| **Single command (quietly)** | ~40.4 ms | **~0.002 ms** | **~20,000×** |
| **Multi-line** (4 commands, do-file) | ~41.9 ms | **~3.2 ms** | **~13×** |
| **Raw StataSO_Execute** (no wrapper) | ~0.002 ms | ~0.002 ms | 1× (baseline) |

### Cold initialisation

| Method | Time | Speedup |
|--------|------|---------|
| Original `stata_setup.config()` (→ pystata) | ~1.50 s | 1× |
| Optimised `pystata_x._config.init()` | **~0.13 s** | **~11×** |
| Optimised `pystata_x.stata_setup.config()` | **~0.13 s** | **~11×** |

### Why cold init is faster

The original `pystata.config.init()` does several expensive things that `pystata_x`'s
init skips:

| Step | Original | pystata-x |
|------|----------|-----------|
| IPython/Jupyter probe | ~100 ms (imports `IPython`, checks for kernel) | **Skipped** |
| Preference-file I/O | ~50 ms (reads `profile.ini` from disk) | **Skipped** |
| Python 2 compat setup | ~30 ms (try/except on every `str()` conversion) | **Removed** |
| `stata_setup` wrapper overhead | ~50 ms (filesystem checks, extra imports) | **Inlined** |
| **Total** | **~1.50 s** | **~0.13 s** |

## libstata_fast — C-level performance optimisation

`src/stata-fast/libstata_fast.{dylib,so}` is a minimal C shared library
that wraps the raw StataSO_* API (`ClearOutputBuffer` + `Execute` +
`GetOutputBuffer`) into a **single C function call**, eliminating all
Python overhead from the hot path.

**Why not a subprocess/pipe approach?** Pipes add syscall + context-switch
overhead that is *slower* than a direct in-process call.  The bottleneck
was Python overhead (~29 µs per call), not the Stata engine (~1 µs).

The direct C wrapper achieves this per-command timeline:

| Phase | Time |
|-------|------|
| ctypes call + C function dispatch | ~0.2 µs |
| `StataSO_ClearOutputBuffer` | ~0.0 µs |
| `StataSO_Execute` | ~0.8 µs |
| `StataSO_GetOutputBuffer` | ~0.3 µs |
| Memory copy + decode | ~1.0 µs |
| **Total** | **~2.3 µs** |

| Metric | Baseline (Python) | `libstata_fast` | Speedup |
|--------|------------------|-----------------|---------|
| Single command (`display 1+1`) | 36.8 µs | **2.3 µs** | **16×** |
| Cold init (standard) | 125 ms | **125 ms** | same |
| **Fork-based cold init** | — | **1.2 ms** | **104×** |
| Throughput | ~25k ops/s | **~435k ops/s** | **17×** |

**Fork pattern**: call `stata_init()` once in a master process, then
`os.fork()` workers — forked children inherit the fully initialised
Stata engine in ~1 ms instead of 125 ms.

See `src/stata-fast/README.md` for the full API, build instructions, and
architecture decisions.

## Project Structure

```
src/
├── pystata_x/
│   ├── __init__.py              # Package entry point
│   ├── _config.py               # Fast Stata initialisation (no IPython/py2 compat)
│   ├── _core.py                 # Fast command execution (direct StataSO_Execute)
│   ├── _stata_fast.py           # Python ctypes bridge to libstata_fast
│   └── stata_setup.py           # Drop-in replacement for PyPI `stata-setup`
├── stata-fast/
│   ├── README.md                # Full documentation
│   ├── Makefile                 # Build system
│   ├── stata_fast.h             # C API header
│   ├── stata_fast.c             # Implementation (~300 lines)
│   └── test_stata_fast.c        # C tests (15 tests)
benchmarks/
├── bench_baseline.py            # Baseline benchmark
├── bench_stata_fast.py          # libstata_fast latency benchmark
├── bench_stata_fast_full.py     # Full benchmark suite
├── bench_stata_fast_fork.py     # Fork-based cold init benchmark
└── history/                     # Benchmark result history (JSON)
```

## Toolchain Requirements

### macOS (ARM64 / x86_64)

| Tool | Version | Install |
|------|---------|---------|
| C compiler | clang (Xcode CLT) | `xcode-select --install` |
| Build system | CMake ≥ 3.20 | `brew install cmake` or `pip install cmake` |
| Python | ≥ 3.10 | `brew install python` or `uv python install` |
| capstone | ≥ 5.0.0 | `pip install capstone` |
| Stata | StataNow / Stata 18+ | — |

### Linux (x86_64 / ARM64)

| Tool | Version | Install |
|------|---------|---------|
| C compiler | gcc or clang | `apt install gcc cmake` / `yum install gcc cmake` |
| Build system | CMake ≥ 3.20 | `apt install cmake` / `pip install cmake` |
| Python | ≥ 3.10 | `apt install python3` or `uv python install` |
| capstone | ≥ 5.0.0 | `pip install capstone` |
| Stata | StataNow / Stata 18+ | — |

### Windows (x86_64 native)

| Tool | Version | Install |
|------|---------|---------|
| C compiler | MSVC (VS BuildTools) or MinGW-w64 | `winget install Microsoft.VisualStudio.2022.BuildTools` or `scoop install mingw` |
| Build system | CMake ≥ 3.20 | `winget install Kitware.CMake` |
| Python | ≥ 3.10 (64-bit) | `python.org` or `scoop install python` |
| capstone | ≥ 5.0.0 | `pip install capstone` (win_amd64 wheel available) |
| Stata | StataNow / Stata 18+ | — |

### Windows (ARM64 → x86_64 target) ⚠️

On ARM64 Windows, Stata is an x86_64 binary running under emulation.  The C
extension must be compiled for **x86_64** to match Stata's architecture.

| Tool | Version | Install |
|------|---------|---------|
| C compiler | LLVM MinGW (x86_64 cross) | `winget install MartinStorsjo.LLVM-MinGW.UCRT` |
| Build system | CMake ≥ 3.20 | `winget install Kitware.CMake` |
| C build | MinGW Makefiles | `cmake -G "MinGW Makefiles" -DCMAKE_C_COMPILER=x86_64-w64-mingw32-gcc` |
| Python (ARM64) | ≥ 3.10 | `python.org` — works for **unit tests only** |
| Python (x86_64 for Stata) | ≥ 3.10 | Needed for Stata integration tests (ARM64 Python cannot load x86_64 DLLs) |
| capstone | **≥ 6.0.0a5** required | `pip install capstone` — 5.x has no win_arm64 wheel and fails to build from source (needs MSVC nmake) |
| Stata | StataNow / Stata 18+ (x86_64) | `C:\Program Files\StataNow19\` |

**⚠️ Architecture mismatch on ARM64 Windows**: Python on ARM64 Windows loads
DLLs with `ctypes.CDLL`.  ARM64 Python can only load ARM64 DLLs.  Stata's
`se-64.dll` is x86_64, so it can only be loaded from an **x86_64 Python process**
(running under emulation).  Options:

1. **Use Stata's embedded Python** — run tests inside Stata via `python:` blocks
   (Stata launches its own x86_64 Python interpreter).
2. **Install a separate x86_64 Python** — e.g. via `scoop install python` after
   forcing x86_64 architecture, or download `python-3.14.5-amd64.exe` from
   python.org.  The x86_64 interpreter runs under emulation and can load
   Stata's DLLs.
3. **Unit tests only** — the 126 unit tests in `tests/unit/` mock `ctypes.cast`
   and require no Stata DLL, so they pass with ARM64 Python.

## Cross-platform

Shared-library discovery in `_config.py` supports macOS, Linux, and Windows:

| Platform | Library name | Search path |
|----------|-------------|-------------|
| macOS | `libstata-{be,se,mp}.dylib` | `Stata{B,E,MP}E.app/Contents/MacOS/` |
| Linux | `libstata-{be,se,mp}.so` | `{st_path}/` |
| Windows | `libstata-{be,se,mp}.dll` | `{st_path}/` |

## Licence

- Our modules (`_config.py`, `_core.py`, `stata_setup.py`, `__init__.py`,
  and all files under `benchmarks/`) are original work, released under the
  **GNU Affero General Public License v3.0**.
- The PyPI ``stata-setup`` package (v0.1.3, StataCorp LLC) is Apache 2.0
  licenced — our `stata_setup.py` provides the same public API with a
  completely rewritten implementation under AGPL-3.0.
