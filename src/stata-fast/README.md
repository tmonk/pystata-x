# libstata_fast — Lean C wrapper around Stata's engine API

A minimal C shared library that wraps `libstata-{edition}.{dylib,so}` into a
single-call `execute()` API, eliminating all Python overhead from the hot path.

## The Problem

The original `pystata-x` executes a Stata command via **three separate ctypes
calls** per command:

```
Python → ClearOutputBuffer → Execute → GetOutputBuffer → Python
```

Each ctypes call incurs Python function-call overhead, encoding/decoding, and
buffer management — adding **~29 µs** of Python tax on top of the actual Stata
engine time (~1.1 µs).  Total round-trip: **~30–40 µs**.

## The Solution

`libstata_fast` bundles all three operations into a single C function, called
once from Python:

```
Python → one ctypes call → libstata_fast → clear + execute + get_output → return
```

Total round-trip: **~2.3 µs** — a **16× speedup**.

## Performance

Benchmarked on macOS 15 (Apple M3 Max):

| Metric | Baseline (pystata-x) | libstata_fast | Speedup |
|--------|---------------------|---------------|---------|
| **Cold init** (optimized, no -pyexec) | 125 ms | **~19 ms** | **6.6×** |
| **Fork-based cold init** (pre-initialized master) | — | **1.2 ms** | **104×** |
| **Single command** (`display 1+1`) | 36.8 µs | **2.3 µs** | **16×** |
| **Throughput** | ~25k ops/s | **~435k ops/s** | **17×** |
| **Multi-line batch** (regression, 10k obs) | 10 ms | **10 ms** | ~same (engine-bound) |
| **Output drain** | 0.3 µs | **0.8 µs** | — |

### How the speed is achieved

1. **One ctypes call instead of three** — C clears the buffer, executes, and reads
   output in a single function.
2. **No Python string encoding/decoding** — the C library handles raw bytes
   and returns a `char*`; Python decodes only once per call.
3. **Zero Python wrapper overhead** — `_stata_fast.py`'s `execute()` is
   literally one `ctypes` call and one `decode()`.
4. **Fork-based reuse** — call `os.fork()` from a pre-initialised master
   process to get workers with Stata ready in ~1 ms (vs 125 ms for
   `StataSO_Main`).

## Architecture Decisions

### Why not a subprocess/pipe approach? (What we abandoned)

The original plan was to spawn a headless Stata subprocess and communicate via
Unix pipes.  We abandoned it because:

- **Pipes add latency** — each command requires a `write()` syscall, a context
  switch to the Stata process, a `read()` syscall, and a context switch back.
  This is *slower* than a direct in-process function call.
- **Full buffering** — when stdout is a pipe, Stata's C runtime uses full
  buffering (4 KB blocks), so output doesn't arrive until the buffer fills or
  Stata exits.  This causes hangs in naive read loops.
- **Text parsing** — we'd need to detect command boundaries via sentinel
  strings (`@@SF_DONE|rc=…@@`) in the text stream, adding complexity and
  fragility.
- **Process management** — crash recovery, orphan cleanup, signal handling
  all add complexity with zero performance benefit.

The direct-wrapper approach (this library) is **simpler, faster, and more
reliable**.

### Why not reverse-engineer StataSO ourselves?

The StataSO_* functions (`StataSO_Main`, `StataSO_Execute`, etc.) are
exported by Stata's proprietary shared library (`libstata-se.dylib`).  We load
them via `dlopen`/`dlsym` and call them directly — no reverse engineering
needed.  This gives us the full speed of the Stata engine without needing to
reimplement it.

### Why the fork pattern for cold init?

`StataSO_Main` takes ~125 ms to initialise the Stata engine (license check,
loading ado files, etc.).  If your workflow spawns many short-lived Python
processes, this cost adds up.

The fork pattern: one "master" process calls `StataSO_Main` once, then
`os.fork()`s worker processes.  Forked children inherit the fully initialised
Stata engine and can execute commands immediately — no re-init needed.

```python
# Master process (once)
sf.init("/Applications/StataNow", "se")

# Fork a worker — Stata is ready in ~1 ms
pid = os.fork()
if pid == 0:
    out, rc = sf.execute("display 1+1")
    os._exit(0)
```

**Caveat**: This depends on `libstata` being fork-safe.  We tested 100×
sequential forks and all children executed successfully.  Background threads
(license checks, etc.) may behave unpredictably after fork — test in your
deployment environment.

## C API

```c
// Initialise Stata engine (loads libstata, calls StataSO_Main)
stata_ctx* stata_init(const char* st_path, const char* edition, int splash);

// Execute a Stata command — one call does ClearBuffer + Execute + GetOutputBuffer
int stata_execute(stata_ctx* ctx, const char* command, int echo,
                  char** output, size_t* out_len, int* retcode);

// Read output buffer (caller must free via stata_free)
char* stata_get_output(stata_ctx* ctx);

// Clear output buffer
void stata_clear_output(stata_ctx* ctx);

// Interrupt a running command
int stata_set_break(stata_ctx* ctx);

// Shut down Stata engine (may call exit())
void stata_shutdown(stata_ctx* ctx);

// Last error message
const char* stata_last_error(stata_ctx* ctx);

// Free strings returned by the library
void stata_free(char* ptr);
```

Error codes: `STATA_OK` (0), `STATA_ERR` (-1), `STATA_NOMEM` (-2),
`STATA_NOT_INIT` (-6).

## Python API (`pystata_x._stata_fast`)

```python
import sys
sys.path.insert(0, "src")
from pystata_x import _stata_fast as sf

sf.init("/Applications/StataNow", "se", splash=False)

# Single command — one ctypes call, ~2.3 µs
output, rc = sf.execute("display 1+1")

# Multi-line — automatically writes temp do-file and includes it
output, rc = sf.execute("sysuse auto, clear\nregress price mpg weight")

# With echo
output, rc = sf.execute("display 3+4", echo=True)
```

## Build

### CMake (recommended, cross-platform)

```bash
# Configure (adjust STATA_PATH for your installation)
cmake -S src/stata-fast -B src/stata-fast/build \
    -DSTATA_PATH="/Applications/StataNow" \
    -DSTATA_EDITION=se

# Build
cmake --build src/stata-fast/build

# Test
cd src/stata-fast/build && ctest -V
```

### Makefile (macOS/Linux quick builds)

```bash
cd src/stata-fast
make          # → libstata_fast.dylib (macOS) / libstata_fast.so (Linux)
make test     # build + run C test
make clean
```

### Convenience script (installs into Python package)

```bash
python3 build_c.py --release
```

Requires: CMake >= 3.20, C99 compiler, `libstata-{be,se,mp}.{dylib,so,dll}` installed.

## Platform Support

| Platform | Status |
|----------|--------|
| macOS (ARM64) | ✅ Tested (M3 Max) |
| macOS (x86_64) | ✅ Compiles, untested |
| Linux (x86_64) | 🟡 Code ready, untested |
| Linux (ARM64) | 🟡 Code ready, untested |
| Windows (x86_64) | 🟡 Code ready, untested |
| Windows (ARM64) | 🟡 Code ready, cross-compiled via cibuildwheel |

## File Structure

```
src/stata-fast/
├── README.md                  # This file
├── Makefile                   # Build system (macOS + Linux)
├── stata_fast.h               # Public C API header
├── stata_fast.c               # Implementation (~300 lines)
├── test_stata_fast.c          # C test (15 tests)

src/pystata_x/
├── _stata_fast.py             # Python ctypes bridge

benchmarks/
├── bench_baseline.py          # Original baseline benchmark
├── bench_stata_fast.py        # Latency benchmark
├── bench_stata_fast_full.py   # Full benchmark suite
├── bench_stata_fast_fork.py   # Fork-based cold init benchmark
├── history/                   # Archived results (JSON)
```

## License

AGPL-3.0-only — see repository root.
