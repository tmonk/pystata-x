# CHANGELOG

<!-- version list -->

## v0.2.0 (2026-05-21)

### Chores

- **gitignore**: Ignore local stata-fast build artifacts
  ([`6743657`](https://github.com/tmonk/pystata-x/commit/67436571474c1399278e4f22b0dadf35e77e2a35))

### Features

- **stata-fast**: Add C source and build files
  ([`18b3e98`](https://github.com/tmonk/pystata-x/commit/18b3e98a51bcfc72eb3fd9a3ad831dedbf15d5c8))


## v0.1.3 (2026-05-19)

### Continuous Integration

- **release**: Remove redundant PyPI publish workflow dispatch
  ([`70f55e3`](https://github.com/tmonk/pystata-x/commit/70f55e35fd07f6544abf423b5b71dc9d8b4a0e27))

### Performance Improvements

- **init**: Defer engine bootstrap to reduce config latency
  ([`2f0781a`](https://github.com/tmonk/pystata-x/commit/2f0781a3609716a089c00ef9d13c2834e941c388))

- **init**: Inline engine bootstrap for fast first execute
  ([`bcd7b4a`](https://github.com/tmonk/pystata-x/commit/bcd7b4a14a8ee04c4112c56de80fee05cc524dbd))

### Testing

- **perf**: Add cold-start initialization benchmark
  ([`035c99b`](https://github.com/tmonk/pystata-x/commit/035c99bcdde402702f417fedc653acbeb08ee346))


## perf/init-10x (unreleased — exploration branch)

### Performance

- **Init time reduced from ~126 ms to ~108 ms (15% improvement)**
  via aggressive import trimming. The Stata engine bootstrap
  (``StataSO_Main``, ~78 ms) still runs during ``config()`` so
  that the first ``execute()`` / ``run()`` call has no additional
  startup latency (~7 ms for a basic command).

- **Lazy ``importlib.metadata``**: The ``pystata_x.__version__``
  string is now resolved on first access via ``__getattr__``,
  avoiding the ~30 ms cost of importing ``importlib.metadata``
  at module load time.

- **Lazy ``pathlib`` / ``platform`` / ``tempfile`` / ``typing``**:
  These modules are now imported only in the functions that need
  them, saving ~12 ms of module-level import time.

- **Cold-start benchmark**: New ``benchmarks/bench_cold_init.py``
  measures total subprocess wall time and per-phase breakdown.

### Reverse-engineering findings

- **Native ``stata-se -q``** starts in ~30 ms (warm) / ~132 ms (cold
  subprocess).  Our previous in-process ``StataSO_Main`` call took
  ~81 ms, suggesting the Stata C engine bootstrap is inherently
  ~75–85 ms regardless of whether called from the native binary or
  from Python via ctypes.

- **argv experimentation**: ``StataSO_Main`` accepts ``-q`` (quiet),
  ``-pyexec <path>`` (embedded Python path), and a leading empty
  argv[0].  The combination ``["", "-q", "-pyexec", ...]`` suppresses
  the splash/license output (vs ``["-q", "-pyexec", ...]`` which
  produces 829 bytes of output).  No other flag combination tested
  (``-b``, ``-s``, ``-k``) worked with the shared-library API.

- **Environment variables**: ``TMPDIR=/tmp`` and ``STATA_NOLOGO=1``
  showed small (~2–5 ms) improvements but within noise (SD ~12 ms).
  No env var reliably reduces StataSO_Main below ~70 ms.

- **ctypes dlopen flags**: ``RTLD_NOW`` crashes on macOS (not
  supported for dylibs). ``RTLD_GLOBAL`` made no measurable
  difference.  The default ``cdll.LoadLibrary`` (``RTLD_LAZY``) is
  optimal.

- **Library loading overhead**: ``cdll.LoadLibrary`` takes ~9.5 ms,
  measured separately from ``StataSO_Main``.  This is macOS dyld
  resolving and loading ``libstata-se.dylib`` and its dependencies
  (BLAS, LAPACK, Arrow, Parquet, gfortran, etc.).

**Implication**: The remaining init time is dominated by
StataCorp's C-level engine bootstrap which we cannot modify.
The most effective optimization was deferring the bootstrap to
first command execution rather than performing it during
``config()``.

## v0.1.2 (2026-05-16)

### Bug Fixes

- Mark semantic-release versioning tests as optional
  ([`6574bee`](https://github.com/tmonk/pystata-x/commit/6574bee84cae02d62a095bf3228aef7426d2126e))


## v0.1.1 (2026-05-16)

### Bug Fixes

- Align CI environment with stata-agent patterns
  ([`ddaa208`](https://github.com/tmonk/pystata-x/commit/ddaa208016c7b2b25434edcecd26e78a58369ea2))

- Improve Stata detection and init; add newline
  ([`c4703fd`](https://github.com/tmonk/pystata-x/commit/c4703fd90413ab1cc047c2cd81d697bd16be04b6))

- Restore python-semantic-release for automatic tag/release creation
  ([`44a7837`](https://github.com/tmonk/pystata-x/commit/44a7837ea51571b2502c33af413195c9f5a8f380))

- **ci**: Remove hardcoded version assert from clean install step
  ([`e87956c`](https://github.com/tmonk/pystata-x/commit/e87956cf5b26f3c8593aa2a8e94638b066dcb081))

### Build System

- Switch to hatch-vcs for fully dynamic git-based versioning
  ([`9dbd2f8`](https://github.com/tmonk/pystata-x/commit/9dbd2f8b2f4f6760fc693f5b8227ecc61d409e50))

### Chores

- **ci**: Remove auto-publish step from release workflow
  ([`836329c`](https://github.com/tmonk/pystata-x/commit/836329cdcb93d0d67590932128e682f2fa1b4720))

### Continuous Integration

- Add fast/slow CI test jobs; pytest xdist
  ([`91f6fe0`](https://github.com/tmonk/pystata-x/commit/91f6fe0eac17846a7833ec6f8652e90686d3cfd3))

- Cache .venv directory with actions/cache
  ([`3f57fa2`](https://github.com/tmonk/pystata-x/commit/3f57fa28a3944d22ff8c1511c91adb45aeb1563e))

- Remove dependency on test-fast for test-slow
  ([`350aaa4`](https://github.com/tmonk/pystata-x/commit/350aaa40f3e8acc5da83d95720a92597dc334ac0))

- Run only fast tests in CI, remove slow test job
  ([`edd359d`](https://github.com/tmonk/pystata-x/commit/edd359d66c743e655f5e847730027f0451ecb4c3))

- Speed up dependency install
  ([`e2db1b6`](https://github.com/tmonk/pystata-x/commit/e2db1b6306094e83c41df8ca21c8ca28c3ea6127))

- **workflows**: Consolidate fast and slow test jobs into a single job
  ([`517b12e`](https://github.com/tmonk/pystata-x/commit/517b12efa2e002df9338adda9ac427aa0559e409))


## v0.1.0 (beta)

Initial release of pystata-x — a fast, independent drop-in replacement for StataCorp's pystata.

### Features

- **Fast command execution**: Direct `StataSO_Execute()` calls bypass the polling-thread bottleneck, delivering ~10,000–20,000× speedup on short commands.
- **Optimised cold initialisation**: Skips IPython probe, preference-file I/O, Python 2 compat setup, and extraneous wrapper overhead — ~11× faster than the original `stata_setup`.
- **Vendor-compatible `run()`**: Drop-in for `pystata.run()` with identical signature and behaviour.
- **`execute()` (fast path)**: Returns `(output, rc)` tuple — not in the vendor API.
- **`config` module**: Init, status, and settings — mirrors the vendor's `pystata.config`.
- **Cross-platform**: Shared-library discovery for macOS, Linux, and Windows.
- **`track_graphs` support**: Bundled graph queries for Stata graphs.
