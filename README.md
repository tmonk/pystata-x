# stata-fast

Optimised fork of StataCorp's **pystata** module.  Provides a drop-in
`stata_setup` initialiser that delivers **~10–20,000×** speedup on
command execution and **~11×** faster cold Stata initialisation.

## Quick Start

```python
import sys
sys.path.insert(0, "path/to/stata-fast/src")

from stata_fast.stata_setup import config
config("/Applications/StataMP", "mp", splash=False)

# Now use pystata as normal — our optimised run() is monkey-patched
from pystata import stata
stata.run("sysuse auto, clear")
```

Or use our module directly:

```python
from stata_fast._core import run

output, rc = run("display 1+1")
print(output)  # "2"
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
output streaming in as commands execute, like a live terminal.  The polling
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
terminal or notebook is needed.  The polling thread is **pure overhead**.

Our `_core.run()` skips the thread entirely and calls
`StataSO_Execute()` directly, then drains the output buffer once after
execution.  This is the same approach used by `StataClient._stata_run()`
in the `stata-agent` project.

## Benchmark Results

Measured on macOS (StataSE, Apple Silicon M4) using
`benchmarks/run_benchmarks.py`.  Each test runs in a **fresh subprocess**
(Stata initialised once per test) with warm-up iterations before timing.
Times are the mean of multiple iterations measured via
`time.perf_counter()`.

### Command execution

| Test | Original pystata | stata-fast | Speedup |
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
| Optimised `_config.init()` | **~0.13 s** | **~11×** |
| Optimised `stata_setup.config()` | **~0.13 s** | **~11×** |

### Why cold init is faster

The original `pystata.config.init()` does several expensive things that our
`_config.init()` skips:

| Step | Original | stata-fast |
|------|----------|-----------|
| IPython/Jupyter probe | ~100 ms (imports `IPython`, checks for kernel) | **Skipped** |
| Preference-file I/O | ~50 ms (reads `profile.ini` from disk) | **Skipped** |
| Python 2 compat setup | ~30 ms (try/except on every `str()` conversion) | **Removed** |
| `stata_setup` wrapper overhead | ~50 ms (filesystem checks, extra imports) | **Inlined** |
| **Total** | **~1.50 s** | **~0.13 s** |

## Project Structure

```
src/stata_fast/
├── __init__.py              # Package entry point
├── _config.py               # Fast Stata initialisation (no IPython/py2 compat)
├── _core.py                 # Fast command execution (direct StataSO_Execute)
├── stata_setup.py           # Drop-in replacement for PyPI `stata-setup`
└── vendor/
    └── pystata/             # Original pystata source (reference copy)
benchmarks/
├── run_benchmarks.py        # Comprehensive benchmark runner
└── history/                 # Benchmark result history
```

## Cross-platform

Shared-library discovery in `_config.py` supports macOS, Linux, and Windows:

| Platform | Library name | Search path |
|----------|-------------|-------------|
| macOS | `libstata-{be,se,mp}.dylib` | `Stata{B,E,MP}E.app/Contents/MacOS/` |
| Linux | `libstata-{be,se,mp}.so` | `{st_path}/` |
| Windows | `libstata-{be,se,mp}.dll` | `{st_path}/` |

## ../stata-agent Compatibility

The `stata_fast.stata_setup` module exports the same function signature as
the PyPI ``stata-setup`` package:

```python
def config(path: str, edition: str, splash: bool = True) -> None
```

This matches the call made by `stata-agent/src/stata_agent/stata_client.py`:

```python
stata_setup.config(root, edition_lower, splash=False)
```

To switch `stata-agent` to use the optimised version, change the import:

```diff
- import stata_setup
+ import sys; sys.path.insert(0, "path/to/stata-fast/src")
+ from stata_fast.stata_setup import config as stata_setup_config
```

(Or install `stata-fast` as a dependency and use `from stata_fast.stata_setup
import config`.)

## Licence

- Our modules (`_config.py`, `_core.py`, `stata_setup.py`, `__init__.py`,
  and all files under `benchmarks/`) are original work, released under the
  **GNU Affero General Public License v3.0**.
- The `vendor/pystata/` directory (excluded from git via `.gitignore`)
  contains a reference copy of StataCorp's proprietary pystata module.  It
  has no open-source licence — use of this code is governed by your Stata
  licence agreement.
- The PyPI ``stata-setup`` package (v0.1.3, StataCorp LLC) is Apache 2.0
  licenced — our `stata_setup.py` provides the same public API with a
  completely rewritten implementation under AGPL-3.0.
