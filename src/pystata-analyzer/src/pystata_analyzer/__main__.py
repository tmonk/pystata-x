"""pystata-analyzer CLI — analyze Stata shared libraries.

Usage:
    python -m pystata_analyzer <path> [flags]

Flags:
    --report                Full analysis report (StataBinary)
    --catalog               Catalog all dispatch functions
    --protocol NAME         Protocol analysis for one function
    --full-protocol NAME    Comprehensive protocol analysis
    --entry-points NAME     Detect multi-entry points
    --trace NAME            Trace thunks and disassemble
    --find-strings          Search for string references in .data
    --analyze-strings       Analyze all discovered string references
    --pool-catalog          Catalog pool allocations
    --search PATTERN        Search dispatch table for matching functions
    --health                Cache health check

Framework flags (uses Framework class with plugins & registry):
    --full-report           Run full pipeline and write report files
    --discover              Auto-discover patterns and update registry
    --registry-add NAME JSON    Add a pattern to the registry
    --registry-list         List all registered patterns
    --registry-save PATH    Save registry to JSON file
    --registry-load PATH    Load registry from JSON file
    --plugin LIST           Comma-separated plugin names to load
    --plugin-dir PATH       Additional plugin directory
    --generate-docs         Generate documentation (analysis + API)
    --diff OTHER_PATH       Compare with another binary
    --interactive           Interactive REPL mode
    --output DIR            Output directory for generated docs (default: .)
"""
import argparse
import json
import os
import sys
from typing import Any

from pystata_analyzer import (
    StataBinary, Framework, PatternRegistry,
)


# ═════════════════════════════════════════════════════════════════════
#  Legacy commands (StataBinary-based)
# ═════════════════════════════════════════════════════════════════════

def _load_binary(path: str) -> StataBinary:
    b = StataBinary.from_cache(path, min_version=2)
    if b is None:
        b = StataBinary(path)
        b.analyze()
    return b


def cmd_report(b: StataBinary) -> None:
    if not b._analyzed:
        b.analyze()
    print(b.report())


def cmd_catalog(b: StataBinary) -> None:
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
    if not b._analyzed:
        b.analyze()
    proto = b.analyze_protocol(name)
    print(json.dumps(proto, indent=2, default=str))


def cmd_full_protocol(b: StataBinary, name: str) -> None:
    if not b._analyzed:
        b.analyze()
    proto = b.analyze_full_protocol(name)
    print(json.dumps(proto, indent=2, default=str))


def cmd_entry_points(b: StataBinary, name: str) -> None:
    if not b._analyzed:
        b.analyze()
    entries = b.trace_entry_points(name)
    print(json.dumps(entries, indent=2, default=str))


def cmd_trace(b: StataBinary, name: str) -> None:
    if not b._analyzed:
        b.analyze()
    vaddr = b.symbols.get(name)
    if vaddr:
        print(f"Disassembly of {name} at 0x{vaddr:x}:")
        print(b.disassemble(vaddr, 256))


def cmd_find_strings(b: StataBinary) -> None:
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
    cmd_find_strings(b)
    if b._analyzed:
        print("\nCross-references to st_* names:")
        for idx, name, flags in getattr(b, "_st_entries", []):
            print(f"  [{idx:4d}] {name:40s} flags={flags}")


def cmd_pool_catalog(b: StataBinary) -> None:
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
    if not b._analyzed:
        b._analyzed = True
    health = b.cache_health()
    print(json.dumps(health, indent=2, default=str))


# ═════════════════════════════════════════════════════════════════════
#  Framework commands (Framework-based)
# ═════════════════════════════════════════════════════════════════════

def _load_framework(path: str, args: Any) -> Framework:
    """Load Framework with plugins from CLI args."""
    plugin_names = []
    if args.plugin:
        plugin_names = [n.strip() for n in args.plugin.split(",") if n.strip()]
    # Map names to plugin classes
    from pystata_analyzer.plugin import BUILTIN_PLUGINS as _BP, Plugin
    plugin_instances = []
    for pname in plugin_names:
        cls = _BP.get(pname)
        if cls:
            plugin_instances.append(cls())
        else:
            print(f"Warning: unknown plugin {pname!r}, skipping", file=sys.stderr)
    return Framework(
        path,
        auto_cache=True,
        plugins=plugin_instances,
        plugin_dir=args.plugin_dir,
    )


def cmd_full_report(path: str, args: Any) -> int:
    """Run full pipeline and write report files."""
    fw = _load_framework(path, args)
    fw.analyze_all()
    written = fw.generate_report(args.output)
    print(f"[framework] Report written to {args.output}/")
    for name, fpath in written.items():
        print(f"  {name} → {fpath}")
    return 0


def cmd_discover(path: str, args: Any) -> int:
    """Auto-discover patterns and update registry."""
    fw = _load_framework(path, args)
    report = fw.analyze_all()
    new = report.get("new_patterns", [])
    print(f"[framework] Discovered {len(new)} new patterns:")
    for p in new:
        print(f"  {p['name']} ({p['type']}) — {p.get('protocol', '')}")
    # Save auto-detected registry
    reg_path = os.path.join(args.output, "registry_auto.json")
    fw.registry.save(reg_path, tier="auto_detected")
    print(f"[framework] Auto-detected registry saved to {reg_path}")
    return 0


def cmd_registry_add(args: Any) -> int:
    """Add a pattern to the registry."""
    name, json_str = args.registry_add
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        print(f"Error: invalid JSON: {e}", file=sys.stderr)
        return 1
    reg = PatternRegistry()
    reg.add(name, data, description=f"CLI-added pattern: {name}")
    print(f"[registry] Added pattern: {name}")
    return 0


def cmd_registry_list(args: Any) -> int:
    """List all registered patterns."""
    reg = PatternRegistry()
    for entry in reg.list():
        print(f"  {entry.name:40s} type={entry.pattern_type:15s} "
              f"source={entry.source:12s} tags={entry.tags}")
    stats = reg.stats()
    print(f"\nTotal: {stats['total']} (hardcoded={stats['hardcoded']}, "
          f"auto={stats['auto_detected']}, user={stats['user_added']})")
    return 0


def cmd_registry_save(args: Any) -> int:
    """Save registry to JSON."""
    reg = PatternRegistry()
    reg_path = reg.save(args.registry_save, tier="auto_detected")
    print(f"[registry] Saved to {reg_path}")
    return 0


def cmd_registry_load(args: Any) -> int:
    """Load registry from JSON and display stats."""
    reg = PatternRegistry.from_file(args.registry_load)
    stats = reg.stats()
    print(f"[registry] Loaded {stats['total']} entries from {args.registry_load}")
    for entry in reg.list(source="auto_detected")[:20]:
        print(f"  {entry.name}")
    if stats['auto_detected'] > 20:
        print(f"  ... and {stats['auto_detected'] - 20} more")
    return 0


def cmd_generate_docs(path: str, args: Any) -> int:
    """Generate documentation."""
    fw = _load_framework(path, args)
    fw.analyze_all()
    written = fw.generate_report(args.output)
    api_path = fw.generate_api_docs(os.path.join(args.output, "docs", "api"))
    print(f"[framework] Documentation generated in {args.output}/")
    for name, fpath in written.items():
        print(f"  {name} → {fpath}")
    print(f"  API docs → {api_path}")
    return 0


def cmd_diff(path: str, args: Any) -> int:
    """Compare with another binary."""
    fw1 = _load_framework(path, args)
    fw2 = _load_framework(args.diff, args)
    fw1.analyze_all()
    fw2.analyze_all()
    diff = fw1.diff(fw2)
    print(json.dumps(diff, indent=2, default=str))
    return 0


def cmd_interactive(path: str, args: Any) -> int:
    """Interactive REPL mode."""
    fw = _load_framework(path, args)
    fw.analyze_all()
    print(f"[framework] Interactive mode. Binary: {path}")
    print(f"[framework] {fw.binary.dispatch_count} dispatch entries, "
          f"{len(fw.binary.symbols)} symbols")
    print("[framework] Commands: report, catalog, protocol <name>, "
          "entries <name>, docs, diff <other>, help, quit")
    import shlex
    while True:
        try:
            line = input("analyze> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line or line == "quit" or line == "exit":
            break
        try:
            parts = shlex.split(line)
            cmd = parts[0]
            if cmd == "report":
                print(fw.report(format="markdown"))
            elif cmd == "catalog":
                cmd_catalog(fw.binary)
            elif cmd == "protocol" and len(parts) > 1:
                cmd_full_protocol(fw.binary, parts[1])
            elif cmd == "entries" and len(parts) > 1:
                cmd_entry_points(fw.binary, parts[1])
            elif cmd == "docs":
                fw.generate_report(".interactive_docs")
                print("[framework] Docs written to .interactive_docs/")
            elif cmd == "help":
                print("Commands: report, catalog, protocol <name>, "
                      "entries <name>, docs, diff <other>, quit")
            else:
                print(f"Unknown command: {cmd}")
        except Exception as e:
            print(f"Error: {e}")
    return 0


# ═════════════════════════════════════════════════════════════════════
#  Main
# ═════════════════════════════════════════════════════════════════════

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Analyze Stata shared library binaries",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("path", help="Path to libstata*.so")

    # Legacy StataBinary flags
    parser.add_argument("--report", action="store_true",
                        help="Full analysis report")
    parser.add_argument("--catalog", action="store_true",
                        help="Catalog all dispatch functions")
    parser.add_argument("--protocol", type=str,
                        help="Protocol analysis for one function")
    parser.add_argument("--full-protocol", type=str,
                        help="Comprehensive protocol analysis")
    parser.add_argument("--entry-points", type=str,
                        help="Detect multi-entry points")
    parser.add_argument("--trace", type=str,
                        help="Disassemble a function")
    parser.add_argument("--find-strings", action="store_true",
                        help="Find strings in .data")
    parser.add_argument("--analyze-strings", action="store_true",
                        help="Analyze all strings")
    parser.add_argument("--pool-catalog", action="store_true",
                        help="Catalog pool allocations")
    parser.add_argument("--search", type=str,
                        help="Search dispatch table")
    parser.add_argument("--health", action="store_true",
                        help="Cache health check")

    # Framework flags
    parser.add_argument("--full-report", action="store_true",
                        help="Run full pipeline and write report files")
    parser.add_argument("--discover", action="store_true",
                        help="Auto-discover patterns and update registry")
    parser.add_argument("--registry-add", type=str, nargs=2,
                        metavar=("NAME", "JSON"),
                        help="Add a pattern to the registry")
    parser.add_argument("--registry-list", action="store_true",
                        help="List all registered patterns")
    parser.add_argument("--registry-save", type=str, metavar="PATH",
                        help="Save registry to JSON file")
    parser.add_argument("--registry-load", type=str, metavar="PATH",
                        help="Load registry from JSON file")
    parser.add_argument("--plugin", type=str, default="",
                        help="Comma-separated plugin names to load")
    parser.add_argument("--plugin-dir", type=str,
                        help="Additional plugin directory")
    parser.add_argument("--generate-docs", action="store_true",
                        help="Generate documentation")
    parser.add_argument("--diff", type=str, metavar="OTHER_PATH",
                        help="Compare with another binary")
    parser.add_argument("--interactive", action="store_true",
                        help="Interactive REPL mode")
    parser.add_argument("--output", type=str, default=".",
                        help="Output directory for generated docs")

    args = parser.parse_args(argv)

    # Framework commands (these get first priority)
    if args.full_report:
        return cmd_full_report(args.path, args)
    if args.discover:
        return cmd_discover(args.path, args)
    if args.registry_add:
        return cmd_registry_add(args)
    if args.registry_list:
        return cmd_registry_list(args)
    if args.registry_save:
        return cmd_registry_save(args)
    if args.registry_load:
        return cmd_registry_load(args)
    if args.generate_docs:
        return cmd_generate_docs(args.path, args)
    if args.diff:
        return cmd_diff(args.path, args)
    if args.interactive:
        return cmd_interactive(args.path, args)

    # Legacy commands
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
        cmd_report(b)

    return 0


if __name__ == "__main__":
    sys.exit(main())
