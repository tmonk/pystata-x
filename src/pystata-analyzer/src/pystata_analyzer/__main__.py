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
    """Load Framework with plugins from CLI args.

    *args* may be None (when called from REPL), in which case
    defaults are used.
    """
    plugin_names = []
    plugin_dir_ = None
    if args is not None:
        if hasattr(args, 'plugin') and args.plugin:
            plugin_names = [n.strip() for n in args.plugin.split(",") if n.strip()]
        if hasattr(args, 'plugin_dir') and args.plugin_dir:
            plugin_dir_ = args.plugin_dir
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
        plugin_dir=plugin_dir_,
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


def cmd_classify(path: str, args: Any) -> int:
    """Run automated classification of unclassified functions."""
    fw = _load_framework(path, args)
    fw.analyze_all()
    result = fw.classify_unclassified(threshold=args.classify_threshold)
    print(f"Classification complete:")
    print(f"  Total unclassified: {result['total_unclassified']}")
    print(f"  Auto-registered: {result['auto_registered']}")
    if result['needs_review']:
        print(f"  Needs review ({len(result['needs_review'])}):")
        for nr in result['needs_review'][:20]:
            print(f"    {nr['name']:35s} confidence={nr['confidence']:.2f} "
                  f"→ {nr.get('inferred_protocol', '?')}")
            for r in nr.get('reasoning', [])[:3]:
                print(f"      - {r}")
    print(f"  Remaining unclassified: {result['remaining_unclassified']}")
    if result['needs_review']:
        print(f"\nRun with --classify-threshold 0.5 to auto-classify more functions.")
    return 0


def cmd_plugin_reload(path: str, args: Any) -> int:
    """Force hot-reload of plugins from plugin-dir."""
    fw = _load_framework(path, args)
    fw.analyze_all()
    updated = fw.reload_plugins()
    if updated:
        print(f"[framework] Reloaded plugins: {', '.join(updated)}")
    else:
        print("[framework] No new plugins discovered.")
    print(f"[framework] Active plugins: {len(fw.plugins)}")
    return 0


def cmd_plugin_add(path: str, args: Any) -> int:
    """Add a built-in plugin by name at runtime."""
    from pystata_analyzer.plugin import BUILTIN_PLUGINS as _BP
    cls = _BP.get(args.plugin_add)
    if cls is None:
        print(f"Error: unknown plugin {args.plugin_add!r}. "
              f"Available: {', '.join(_BP)}", file=sys.stderr)
        return 1
    fw = _load_framework(path, args)
    if not fw._analyzed:
        fw.analyze_all()
    try:
        fw.register_plugin(cls())
        print(f"[framework] Plugin {args.plugin_add!r} registered.")
        print(f"[framework] Active plugins: {len(fw.plugins)}")
        for p in fw.plugins:
            print(f"  {p.name}: {p.description}")
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    return 0


def cmd_interactive(path: str, args: Any) -> int:
    """Interactive TUI/REPL mode.

    Uses ``prompt_toolkit`` for a rich terminal UI with tab-completion,
    syntax highlighting, paging, search, and command history.  Falls back
    to a basic readline loop if prompt_toolkit is not installed.
    """
    fw = _load_framework(path, args)
    fw.analyze_all()

    print(f"[framework] Interactive mode. Binary: {path}")
    print(f"[framework] {fw.binary.dispatch_count} dispatch entries, "
          f"{len(fw.binary.symbols)} symbols")
    print(f"[framework] Type 'help' for commands, 'quit' to exit")

    try:
        _repl_prompt_toolkit(fw, args)
    except ImportError:
        _repl_readline(fw)
    return 0


def _repl_readline(fw: Framework) -> None:
    """Basic readline REPL (fallback when prompt_toolkit unavailable)."""
    import shlex
    commands = {
        "report": "Show full analysis report",
        "catalog": "List all dispatch functions",
        "protocol <name>": "Show protocol analysis for a function",
        "entries <name>": "Show entry points for a function",
        "disasm <name>": "Disassemble a function",
        "search <pattern>": "Search functions by name/pattern",
        "classify": "Run automated classification workflow",
        "docs": "Generate documentation to .interactive_docs/",
        "export <name>": "Export function doc to JSON",
        "diff <other>": "Compare with another binary",
        "plugins": "List loaded plugins",
        "help": "Show this help",
        "quit": "Exit",
    }
    print("Commands:", ", ".join(sorted(commands.keys())))
    while True:
        try:
            line = input("analyze> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line or line in ("quit", "exit"):
            break
        try:
            parts = shlex.split(line)
            cmd = parts[0]
            _execute_repl_command(fw, cmd, parts[1:])
        except Exception as e:
            print(f"Error: {e}")


def _repl_prompt_toolkit(fw: Framework, args: Any) -> None:
    """Rich TUI REPL using prompt_toolkit."""
    from prompt_toolkit import PromptSession
    from prompt_toolkit.completion import Completer, Completion
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.styles import Style
    from prompt_toolkit.formatted_text import HTML
    import shlex
    import os

    # ── Custom completer ──
    class AnalyzerCompleter(Completer):
        def __init__(self, fw):
            self.fw = fw
            self.commands = [
                "report", "catalog", "protocol", "entries",
                "disasm", "search", "classify", "docs",
                "export", "diff", "plugins", "registry", "help", "quit",
            ]

        def get_completions(self, document, complete_event):
            text = document.text_before_cursor
            words = text.split()
            if not words:
                return
            # First word: complete command
            if len(words) == 1:
                for cmd in self.commands:
                    if cmd.startswith(words[0]):
                        yield Completion(cmd, start_position=-len(words[0]))
            # Second word (function name): complete from symbols
            elif len(words) >= 2 and words[0] in (
                    "protocol", "entries", "disasm", "export"):
                prefix = words[-1].lower()
                for sym in sorted(self.fw.binary.symbols):
                    if sym.startswith("_bist_") and prefix in sym.lower():
                        yield Completion(
                            sym, start_position=-len(prefix))

    # ── History ──
    history_path = os.path.expanduser("~/.pystata-analyzer-history")
    history = FileHistory(history_path)

    # ── Style ──
    style = Style.from_dict({
        "prompt": "ansicyan bold",
        "error": "ansired",
        "success": "ansigreen",
    })

    # ── Session ──
    session = PromptSession(
        history=history,
        completer=AnalyzerCompleter(fw),
        style=style,
    )

    # Command dispatch table
    commands = {
        "report": "Show full analysis report",
        "catalog": "List all dispatch functions",
        "protocol <name>": "Show protocol analysis for a function",
        "entries <name>": "Show entry points for a function",
        "disasm <name>": "Disassemble a function",
        "search <pattern>": "Search functions by name or regex pattern",
        "classify": "Run automated classification of unclassified functions",
        "docs": "Generate full documentation to .interactive_docs/",
        "export <name>": "Export function analysis as JSON",
        "diff <other>": "Compare with another binary",
        "plugins": "List loaded plugins",
        "registry": "Show registry stats",
        "help": "Show categorized help",
        "quit": "Exit the TUI",
    }

    # Grouped help
    help_categories = {
        "Analysis": ["report", "catalog", "protocol", "entries",
                     "disasm", "search"],
        "Classification": ["classify"],
        "Documentation": ["docs", "export"],
        "Comparison": ["diff"],
        "Plugins": ["plugins"],
        "Registry": ["registry"],
        "General": ["help", "quit"],
    }

    while True:
        try:
            text = session.prompt(
                HTML("<prompt>analyze></prompt> "),
            )
        except (EOFError, KeyboardInterrupt):
            print()
            break

        line = text.strip()
        if not line or line in ("quit", "exit"):
            break

        try:
            parts = shlex.split(line)
            cmd = parts[0]
            if cmd == "help":
                for category, cmd_list in help_categories.items():
                    print(f"\n  {category}:")
                    for c in cmd_list:
                        desc = commands.get(c, "")
                        print(f"    {c:25s} {desc}")
                print()
            else:
                _execute_repl_command(fw, cmd, parts[1:])
        except Exception as e:
            print(f"Error: {e}")


def _execute_repl_command(fw: Framework, cmd: str,
                          args: list[str]) -> None:
    """Execute a single REPL command."""
    import json
    if cmd == "report":
        print(fw.report(format="markdown"))
    elif cmd == "catalog":
        print(f"{'Function':30s} {'Idx':5s} {'Type':20s} {'Push':6s} {'Ent':4s} {'Err':5s} {'PushC':5s}")
        print("=" * 77)
        for name in sorted(fw.binary.symbols):
            if not name.startswith("_bist_") or name == "_bist_store":
                continue
            r = fw.analyze_function(name)
            di = str(r.get("dispatch_index", "?"))
            pt = (r.get("protocol_type", "?") or "?")[:20]
            ps = "YES" if r.get("uses_push_stack") else "no"
            nc = str(len(r.get("entry_candidates", [])))
            ec = str(len(r.get("error_codes", []) or r.get("error_codes_found", [])))
            pc = str(len(r.get("push_calls", [])))
            print(f"{name:30s} {di:5s} {pt:20s} {ps:6s} {nc:4s} {ec:5s} {pc:5s}")
    elif cmd == "protocol" and len(args) >= 1:
        name = args[0]
        if not name.startswith("_bist_"):
            name = f"_bist_{name}"
        proto = fw.binary.analyze_full_protocol(name)
        print(json.dumps(proto, indent=2, default=str))
    elif cmd == "entries" and len(args) >= 1:
        name = args[0]
        if not name.startswith("_bist_"):
            name = f"_bist_{name}"
        eps = fw.binary.trace_entry_points(name)
        print(json.dumps(eps, indent=2, default=str))
    elif cmd == "disasm" and len(args) >= 1:
        name = args[0]
        if not name.startswith("_bist_"):
            name = f"_bist_{name}"
        vaddr = fw.binary.symbols.get(name)
        if vaddr:
            print(f"Disassembly of {name} at 0x{vaddr:x}:")
            blocks = fw.binary.disassemble_basic_blocks(vaddr, max_size=512)
            for i, block in enumerate(blocks):
                start = block.get("start_vaddr", 0)
                end = block.get("end_vaddr", 0)
                bt = block.get("branch_target")
                ft = block.get("fallthrough")
                insns = block.get("instructions", [])
                print(f"; Block {i}: 0x{start:x}–0x{end:x} ({len(insns)} insns)")
                if bt:
                    print(f";   Branch → 0x{bt:x}")
                if ft:
                    print(f";   Fallthrough → 0x{ft:x}")
                for insn in insns:
                    op = f"{insn['mnemonic']} {insn['op_str']}"
                    print(f"  0x{insn['vaddr']:x}: {op}")
                print()
        else:
            print(f"Function {name} not found")
    elif cmd == "search" and len(args) >= 1:
        import re
        pattern = args[0]
        pat = re.compile(pattern, re.IGNORECASE)
        found = 0
        for name in sorted(fw.binary.symbols):
            if pat.search(name):
                vaddr = fw.binary.symbols[name]
                print(f"  {name:30s} vaddr=0x{vaddr:x}")
                found += 1
        print(f"\n{found} matches for {pattern!r}")
    elif cmd == "classify":
        result = fw.classify_unclassified(
            threshold=getattr(args, "classify_threshold", 0.8))
        print(f"Classification complete:")
        print(f"  Total unclassified: {result['total_unclassified']}")
        print(f"  Auto-registered: {result['auto_registered']}")
        if result['needs_review']:
            print(f"  Needs review ({len(result['needs_review'])}):")
            for nr in result['needs_review'][:10]:
                print(f"    {nr['name']:30s} "
                      f"confidence={nr['confidence']:.2f} "
                      f"→ {nr.get('inferred_protocol', '?')}")
        print(f"  Remaining unclassified: {result['remaining_unclassified']}")
    elif cmd == "docs":
        fw.generate_report(".interactive_docs")
        print("[framework] Docs written to .interactive_docs/")
    elif cmd == "export" and len(args) >= 1:
        name = args[0]
        if not name.startswith("_bist_"):
            name = f"_bist_{name}"
        functions = fw._last_report.get("functions", {})
        result = functions.get(name)
        if result:
            import json
            print(json.dumps(result, indent=2, default=str))
        else:
            print(f"Function {name} not found in report")
    elif cmd == "diff" and len(args) >= 1:
        other_path = args[0]
        try:
            other_fw = _load_framework(other_path, None)
            other_fw.analyze_all()
            diff_result = fw.diff(other_fw)
            print(json.dumps(diff_result, indent=2, default=str))
        except Exception as e:
            print(f"Error comparing with {other_path}: {e}")
    elif cmd == "plugins":
        for p in fw.plugins:
            print(f"  {p.name:30s} v{p.version} — {p.description}")
    elif cmd == "registry":
        stats = fw.registry.stats()
        print(f"Registry: {stats['total']} total "
              f"(hardcoded={stats['hardcoded']}, "
              f"auto={stats['auto_detected']}, "
              f"user={stats['user_added']})")
    else:
        print(f"Unknown command: {cmd}. Type 'help' for available commands.")


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
    parser.add_argument("--classify", action="store_true",
                        help="Run automated classification of unclassified functions")
    parser.add_argument("--classify-threshold", type=float, default=0.8,
                        help="Confidence threshold for auto-classification (0.0-1.0, default 0.8)")
    parser.add_argument("--plugin-reload", action="store_true",
                        help="Force hot-reload of plugins from plugin-dir")
    parser.add_argument("--plugin-add", type=str, metavar="NAME",
                        help="Add a built-in plugin by name at runtime")

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
    if args.classify:
        return cmd_classify(args.path, args)
    if args.interactive:
        return cmd_interactive(args.path, args)
    if args.plugin_reload:
        return cmd_plugin_reload(args.path, args)
    if args.plugin_add:
        return cmd_plugin_add(args.path, args)

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
