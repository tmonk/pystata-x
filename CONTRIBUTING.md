# Contributing

## Getting Started

1. Read [`BUILDING.md`](BUILDING.md) for platform-specific toolchain setup.
2. Read [`docs/BENCHMARKING.md`](docs/BENCHMARKING.md) for the cold-start
   versus per-call trade-off analysis and C fast-path architecture.
3. Read [`src/stata-fast/README.md`](src/stata-fast/README.md) for the C
   extension API and build instructions.
4. Read [`docs/CRACKED_CONVENTIONS.md`](docs/CRACKED_CONVENTIONS.md) for the
   ARM64 `_bist_*` calling convention notes.

## Development Setup

```bash
# Clone and install
git clone https://github.com/tmonk/pystata-x.git
cd pystata-x
pip install -e ".[dev]"

# Build the C extension
cd src/stata-fast
make   # macOS / Linux
# or
cmake -S . -B build && cmake --build build
```

## Codebase Overview

```
src/
├── pystata_x/                  # Python package
│   ├── _config.py              # Stata engine init (dlopen/ctypes)
│   ├── _core.py                # Command execution, SFI wrappers
│   ├── _stata_fast.py          # Python bridge to libstata_fast C extension
│   ├── _sfi_bridge.py          # Manifest-based symbol resolution
│   └── stata_setup.py          # Drop-in for PyPI `stata-setup`
├── stata-fast/                 # C extension
│   ├── stata_fast.c/h          # Core implementation
│   ├── CMakeLists.txt          # Cross-platform build
│   └── Makefile                # macOS/Linux convenience build
```

## Testing

```bash
# Unit tests (no Stata needed)
pytest tests/unit/ -v

# End-to-end tests (Stata must be installed)
pytest tests/e2e/ -v
```

## Code Style

- Python: ruff (`pip install ruff`)
- C: clang-format or manual conformance to existing style

## Pull Request Checklist

- [ ] `pytest tests/unit/` passes
- [ ] `pytest tests/e2e/` passes (if Stata available)
- [ ] C extension compiles without warnings
- [ ] `BUILDING.md` updated if toolchain changes
- [ ] Benchmarks updated if performance changes
