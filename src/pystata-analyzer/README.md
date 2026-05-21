# pystata-analyzer

Standalone binary analysis framework for Stata shared libraries.  
Extracted from the [pystata-x](https://github.com/tom-doerr/pystata-x) project.

## Features

- **ELF64 loader** — pure-ctypes section reader, no external dependencies
- **Dispatch-table scanner** — discovers Stata's internal dispatch table (1686 entries on x86_64) from `.rela.dyn`
- **st\_\* name table** — parses `.data` section for name→dispatch-index mappings
- **Push function discovery** — finds `_pushdbl`, `_pushint`, `_pushstr` in `.text`
- **Protocol analysis** — for any `_bist_*` dispatch function:
  - Entry point detection (multi-entry read/write split)
  - ARG_PTR read detection via RIP-relative resolution
  - Error code extraction with guard context
  - Push-string call detection
  - `analyze_full_protocol()` — comprehensive single-call report
- **Manifest generation** — JSON output with all discovered symbols and offsets
- **Live engine integration** (optional, via `pystata-x`)

## Quick Start

```python
from pystata_analyzer import StataBinary

# Static analysis
ana = StataBinary("/path/to/libstata.so")
ana.analyze()

# Basic info
print(f"Dispatch table: {ana.dispatch_count} entries")
print(f"Symbols: {len(ana.symbols)}")

# Function-level protocol
proto = ana.analyze_full_protocol("_bist_data")
print(f"Protocol type: {proto['protocol_type']}")
print(f"Uses push+stack: {proto['uses_push_stack']}")
print(f"Entry points: {len(proto.get('entry_candidates', []))}")
```

## CLI (future)

```bash
python -m pystata_analyzer /path/to/libstata.so --report
python -m pystata_analyzer /path/to/libstata.so --full-protocol _bist_data
python -m pystata_analyzer /path/to/libstata.so --entry-points _bist_data
```

## Dependencies

- **capstone ≥ 6.0.0a5** — for disassembly (analysis without it still works, but disassembly features are disabled)

## Architecture Notes

The framework understands Stata's x86_64 binary calling conventions:

- **ARG_PTR (0x500C6A0)**: Push functions (`_push_int`, `_push_str`, `_push_double`) store tsmat pointers here and advance by 8 per push. `_save_sp()` reads from here.
- **SP_global (0x500C638)**: SP-resetting dispatch thunks write a data-descriptor address here. The implementation functions often ignore it and read from ARG_PTR instead.
- **tsmat structure**: Data is embedded at offset 0 (double value or GSO pointer). Pool-header check is `tsmat[-0x94] == 0x2b`.
- **Multi-entry dispatch**: Functions like `_bist_data`/`_bist_store` (dispatch[87]) have separate entry points for read (2-arg) and write (3-arg/4-arg) operations.

## Testing

```bash
cd src/pystata-analyzer
pip install -e .
pytest tests/
```

## License

MIT
