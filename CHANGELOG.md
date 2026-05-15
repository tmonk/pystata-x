# CHANGELOG

<!-- version list -->

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
