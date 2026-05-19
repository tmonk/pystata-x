# StataSO_Main Internal Analysis

Reverse-engineering analysis of `StataSO_Main` in `libstata-se.dylib` (arm64 macOS).

## Method

- **Static disassembly**: `otool -tV` on the arm64-thinned dylib, manual analysis
- **Dynamic profiling**: `lldb` breakpoints at each internal function entry, wall-clock timing
- **Timing verification**: `mach_absolute_time` in C test binaries, subprocess-isolated benchmarks

## Function Overview

`StataSO_Main` is at offset `0x6cd030` in `__TEXT,__text` (~700 bytes, ~175 ARM64 instructions).
It initialises the Stata engine by calling these internal functions sequentially:

```
StataSO_Main (entry)
├── Guard check (__StataSO_Main_init flag at 0x3529e49)
├── Argv parsing (looks for "-pyexec" flag at 0x2f53978)
├── bzero / pi_zap / setjmp (error recovery setup)
├── _init_tmp             0x70c958   — temp directory setup
├── _open_prefs           0x67a1d0   — open preferences file
├── _sprefs_init          0x67a34c   — init preferences subsystem
├── _sprefs_load          0x67a40c   — load profile.ini from disk
├── _gi_zap_wins          0x4a5440   — GUI cleanup (no-op headless)
├── _sinit0               0x70b754   — main Stata interpreter init 
├── _runsysprofile        0x6cd2ec   — run sysprofile.do
├── _runprofile           0x6cd490   — run user profile.do
├── _doreq                0x493dd0   — process do-file request (skipped if no do)
└── _python_initialize_so 0x7a989c   — init CPython sub-interpreter (SKIPPED via -pyexec bypass)
StataSO_Main (exit)
```

## Per-Call Timing (lldb breakpoint profiling)

Measured under `lldb` (absolute times inflated ~2× by debugger overhead; relative
proportions are representative):

| Order | Function                 | Time (ms) | %     | Notes                           |
|-------|--------------------------|-----------|-------|---------------------------------|
| 1     | Prologue + setjmp        | ~9        | 5.7%  | Arg parsing, guard, setjmp      |
| 2     | `_init_tmp`              | ~9        | 5.7%  | Temp file setup                 |
| 3     | `_open_prefs`            | ~6        | 3.7%  | File open                       |
| 4     | `_sprefs_init`           | ~7        | 4.1%  | Pref subsystem init             |
| 5     | `_sprefs_load`           | ~5        | 3.0%  | Read profile.ini                |
| 6     | `_gi_zap_wins`           | ~8        | 5.0%  | GUI cleanup                     |
| 7     | `_sinit0`                | ~6        | 3.4%  | Main interpreter init           |
| 8     | `_runsysprofile`         | ~11       | 6.3%  | Read sysprofile.do              |
| 9     | `_runprofile`            | ~5        | 3.0%  | Read profile.do                 |
| **—** | **`_python_initialize_so`** | **~80** | **48%** | **CPython init (when -pyexec passed)** |
|       | Epilogue + return        | ~4        | 2.4%  | Cleanup                         |
|       | **Total**                | **~166**  | **100%** | Under lldb (real: ~100 ms)    |

## Bottleneck Identification

### `_python_initialize_so` (~80 ms, ~48% of init time)

This function initialises the CPython sub-interpreter inside Stata. It:
1. Loads the Python `.so` plugin (`PyInit_stata_plugin`)
2. Starts the CPython runtime (import site, builtins, etc.)
3. Initialises the `sfi` Python module interface

**Trigger**: `StataSO_Main`'s argument parser checks for `-pyexec` at offset `0x2f53978`.
If found, it stores argv[i+1] as the Python executable path.
After all other init completes, it checks `strlen(pyexec_path) > 0` and calls
`_python_initialize_so` if so.

### Other contributors (without -pyexec, ~15 ms total)

| Function              | Est. real time | %     | Notes                          |
|-----------------------|----------------|-------|--------------------------------|
| Prologue + setup      | ~2 ms          | 13%   |                                  |
| `_sinit0`             | ~5 ms          | 33%   | Main engine init (essential)    |
| `_runsysprofile`      | ~2 ms          | 13%   | Profile.do read                 |
| `_runprofile`         | ~1 ms          | 7%    | Profile.do read                 |
| `_sprefs_load`        | ~1 ms          | 7%    | Pref file read                  |
| `_init_tmp`           | ~1 ms          | 7%    | Temp dir                        |
| Other (open, zap, etc)| ~3 ms          | 20%   |                                  |
| **Total**             | **~15 ms**     | **100%** |                                  |

## Bypass Mechanism

The bypass is implemented by manipulating the command-line arguments passed to
`StataSO_Main`. The argument parser is at 0x6cd0b8-0x6cd100 and recognises
only the `-pyexec` flag. By omitting `-pyexec`, the `pyexec_path_buffer` at
0x39d1000+0x324 remains empty (`strlen` returns 0), and `_python_initialize_so`
is skipped via the conditional branch at 0x6cd2a0.

This is implemented in `stata_fast.c`'s `stata_init_engine()` function, which
builds argv as `["", "-q"]` — intentionally omitting the `-pyexec` flag.
The `stata_init()` convenience function calls `stata_load()` + `stata_init_engine()`
and inherits the same behaviour.

**Result**: ~80 ms saved (11.4× speedup for the engine-init phase).

## Results

| Metric | Before | After | Speedup |
|--------|--------|-------|---------|
| StataSO_Main (with -pyexec) | ~93 ms | ~8 ms | **11.4×** |
| Combined init (dlopen + engine) | ~125 ms | ~19 ms | **6.6×** |
| Fork-based init | — | ~1.2 ms | **104×** |
