# CHANGELOG

<!-- version list -->

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
