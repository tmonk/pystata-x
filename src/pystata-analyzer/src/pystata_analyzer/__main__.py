"""pystata-analyzer CLI — analyze Stata shared libraries.

Usage:
    python -m pystata_analyzer <path> [flags]

Flags:
    --report                Full analysis report
    --catalog               Catalog all dispatch functions
    --protocol NAME         Protocol analysis for one function
    --full-protocol NAME    Comprehensive protocol analysis
    --entry-points NAME     Detect multi-entry points
    --trace NAME            Trace thunks and disassemble
    --find-strings          Search for string references in .data
    --analyze-strings       Analyze all discovered string references
    --pool-catalog          Catalog pool allocations referenced by dispatch
    --search PATTERN        Search dispatch table for matching functions
    --health                Cache health check
"""
import argparse
import json
import sys

from pystata_analyzer import StataBinary


def _load_binary(path: str) -> StataBinary:
    """Load and analyze the binary, trying cache first."""
    b = StataBinary.from_cache(path, min_version=2)
    if b is None:
        b = StataBinary(path)
        b.analyze()
    return b


def cmd_report(b: StataBinary) -> None:
    """Full analysis report."""
    if not b._analyzed:
        b.analyze()
    print(b.report())


def cmd_catalog(b: StataBinary) -> None:
    """Catalog all dispatch functions with protocol type."""
    if not b._analyzed:
        b.analyze()
    print(f"{'Function':30s} {'Idx':5s} {'Type':20s} {'Push':6s} {'Ent':4s}")
    print("=" * 67)
    for name in sorted(b.symbols):
        if not name.startswith("_bist_") or name == "_bist_store":
            continue
        proto = b.analyze_full_protocol(name)
        di = str(proto.get("dispatch_index", "?"))
        pt = proto.get("protocol_type", "?")[:20]
        ps = "YES" if proto.get("uses_push_stack") else "no"
        nc = str(len(proto.get("entry_candidates", [])))
        print(f"{name:30s} {di:5s} {pt:20s} {ps:6s} {nc:4s}")


def cmd_protocol(b: StataBinary, name: str) -> None:
    """Protocol analysis for one function."""
    if not b._analyzed:
        b.analyze()
    proto = b.analyze_protocol(name)
    print(json.dumps(proto, indent=2, default=str))


def cmd_full_protocol(b: StataBinary, name: str) -> None:
    """Comprehensive protocol analysis."""
    if not b._analyzed:
        b.analyze()
    proto = b.analyze_full_protocol(name)
    print(json.dumps(proto, indent=2, default=str))


def cmd_entry_points(b: StataBinary, name: str) -> None:
    """Detect multi-entry points."""
    if not b._analyzed:
        b.analyze()
    entries = b.trace_entry_points(name)
    print(json.dumps(entries, indent=2, default=str))


def cmd_trace(b: StataBinary, name: str) -> None:
    """Trace thunks and disassemble."""
    if not b._analyzed:
        b.analyze()
    vaddr = b.symbols.get(name)
    if vaddr:
        print(f"Disassembly of {name} at 0x{vaddr:x}:")
        print(b.disassemble(vaddr, 256))


def cmd_find_strings(b: StataBinary) -> None:
    """Search for string references in .data."""
    if not b._analyzed:
        b.analyze()
    if not b._elf:
        print("No ELF data loaded")
        return
    data = b._elf.section_data.get(".data", b"")
    strings = []
    i = 0
    while i < len(data):
        if 0x20 <= data[i] <= 0x7E:
            start = i
            while i < len(data) and data[i] != 0:
                i += 1
            s = data[start:i].decode("ascii", errors="replace")
            if len(s) >= 4 and not s.startswith("\\") and s.isprintable():
                strings.append((b._elf.data_vaddr + start, s))
        i += 1
    print(f"Found {len(strings)} strings in .data:")
    for vaddr, s in sorted(strings, key=lambda x: x[0])[:50]:
        print(f"  0x{vaddr:x}: {repr(s)}")
    if len(strings) > 50:
        print(f"  ... and {len(strings) - 50} more")


def cmd_analyze_strings(b: StataBinary) -> None:
    """Analyze all string references."""
    # Same as find-strings but also cross-references dispatch entries
    cmd_find_strings(b)
    # Cross-reference with dispatch
    if b._analyzed:
        print("\nCross-references to st_* names:")
        for idx, name, flags in getattr(b, "_st_entries", []):
            print(f"  [{idx:4d}] {name:40s} flags={flags}")


def cmd_pool_catalog(b: StataBinary) -> None:
    """Catalog pool allocations."""
    if not b._analyzed:
        b.analyze()
    print("Pool-header check analysis (scanning dispatch functions):")
    found = 0
    for name in list(b.symbols)[:100]:
        if not name.startswith("_bist_"):
            continue
        try:
            proto = b.analyze_dispatch_fn(name)
            has_pool = "pool_header_check" in json.dumps(proto)
            if has_pool:
                print(f"  {name:30s} → pool check detected")
                found += 1
        except Exception:
            pass
    print(f"\nFound {found} functions with pool-header checks.")


def cmd_search(b: StataBinary, pattern: str) -> None:
    """Search dispatch table for matching functions."""
    if not b._analyzed:
        b.analyze()
    import re
    pat = re.compile(pattern, re.IGNORECASE)
    print(f"Searching for {pattern!r} in {len(b.symbols)} symbols:")
    found = 0
    for name in sorted(b.symbols):
        if pat.search(name):
            vaddr = b.symbols[name]
            di = "?"
            for i, dv in enumerate(getattr(b, "_dispatch_entries", [])):
                if dv == vaddr:
                    di = str(i)
                    break
            print(f"  {name:30s} idx={di:5s} vaddr=0x{vaddr:x}")
            found += 1
    print(f"\n  {found} matches.")


def cmd_health(b: StataBinary) -> None:
    """Cache health check."""
    if not b._analyzed:
        b._analyzed = True
    health = b.cache_health()
    print(json.dumps(health, indent=2, default=str))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Analyze Stata shared library binaries",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("path", help="Path to libstata*.so")
    parser.add_argument("--report", action="store_true", help="Full analysis report")
    parser.add_argument("--catalog", action="store_true", help="Catalog all dispatch functions")
    parser.add_argument("--protocol", type=str, help="Protocol analysis for one function")
    parser.add_argument("--full-protocol", type=str, help="Comprehensive protocol analysis")
    parser.add_argument("--entry-points", type=str, help="Detect multi-entry points")
    parser.add_argument("--trace", type=str, help="Disassemble a function")
    parser.add_argument("--find-strings", action="store_true", help="Find strings in .data")
    parser.add_argument("--analyze-strings", action="store_true", help="Analyze all strings")
    parser.add_argument("--pool-catalog", action="store_true", help="Catalog pool allocations")
    parser.add_argument("--search", type=str, help="Search dispatch table")
    parser.add_argument("--health", action="store_true", help="Cache health check")

    args = parser.parse_args(argv)

    try:
        b = _load_binary(args.path)
    except FileNotFoundError:
        print(f"Error: binary not found: {args.path}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error loading binary: {e}", file=sys.stderr)
        return 1

    if args.report:
        cmd_report(b)
    elif args.catalog:
        cmd_catalog(b)
    elif args.protocol:
        cmd_protocol(b, args.protocol)
    elif args.full_protocol:
        cmd_full_protocol(b, args.full_protocol)
    elif args.entry_points:
        cmd_entry_points(b, args.entry_points)
    elif args.trace:
        cmd_trace(b, args.trace)
    elif args.find_strings:
        cmd_find_strings(b)
    elif args.analyze_strings:
        cmd_analyze_strings(b)
    elif args.pool_catalog:
        cmd_pool_catalog(b)
    elif args.search:
        cmd_search(b, args.search)
    elif args.health:
        cmd_health(b)
    else:
        # Default: show report
        cmd_report(b)

    return 0


if __name__ == "__main__":
    sys.exit(main())
