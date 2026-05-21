"""Framework — unified orchestration for pystata-analyzer.

The ``Framework`` class ties together StataBinary, PatternRegistry, and
the Plugin system into a single pipeline:
    ELF load → dispatch discovery → st_* name parsing → push-fn discovery
    → protocol analysis → knowledge registration → documentation generation

Usage::

    from pystata_analyzer import Framework
    fw = Framework("/path/to/libstata.so")
    fw.analyze_all()
    print(fw.report(format="markdown"))
"""

import json
import os
import time
from typing import Any, Optional

from pystata_analyzer import StataBinary, ELFReader
from pystata_analyzer.registry import PatternRegistry, PatternEntry
from pystata_analyzer.plugin import (
    Plugin, BUILTIN_PLUGINS, discover_plugins, resolve_dependencies,
    _ANALYZE_HOOKS, _REPORT_HOOKS,
)


class Framework:
    """Unified analysis framework for Stata binaries.

    Orchestrates the full pipeline: load binary, run all discovery,
    analyze every dispatch function, register patterns, and generate
    documentation.

    Parameters
    ----------
    binary_path : str
        Path to libstata*.so
    auto_analyze : bool
        If True, run ``analyze_all()`` immediately at construction.
        Default: False.
    auto_cache : bool
        If True, try loading from cache first; save after analysis.
        Default: True.
    plugins : list[Plugin] or None
        Additional plugin instances to register.  Built-in plugins are
        loaded by default unless *skip_builtins* is True.
    skip_builtins : bool
        If True, do NOT load built-in plugins automatically.
    plugin_dir : str or None
        Additional directory to scan for .py plugin files.
    """

    def __init__(self, binary_path: str, *,
                 auto_analyze: bool = False,
                 auto_cache: bool = True,
                 plugins: Optional[list[Plugin]] = None,
                 skip_builtins: bool = False,
                 plugin_dir: Optional[str] = None):
        self.binary_path = binary_path
        self._auto_cache = auto_cache

        # StataBinary (core analysis engine)
        self.binary: StataBinary
        if auto_cache:
            cached = StataBinary.from_cache(binary_path, min_version=2)
            if cached is not None:
                self.binary = cached
            else:
                self.binary = StataBinary(binary_path)
        else:
            self.binary = StataBinary(binary_path)

        # Pattern registry (knowledge base)
        self.registry = PatternRegistry()

        # Plugin system
        self._plugins: list[Plugin] = []
        if not skip_builtins:
            for name, cls in BUILTIN_PLUGINS.items():
                self._plugins.append(cls())
        if plugins:
            self._plugins.extend(plugins)
        discovered = discover_plugins(plugin_dir)
        self._plugins.extend(discovered)
        try:
            self._plugins = resolve_dependencies(self._plugins)
        except ValueError as e:
            raise ValueError(f"Plugin dependency resolution failed: {e}") from e

        # Analysis state
        self._analyzed = False
        self._last_report: dict[str, Any] = {}

        if auto_analyze:
            self.analyze_all()

    # ═════════════════════════════════════════════════════════════════
    #  Properties
    # ═════════════════════════════════════════════════════════════════

    @property
    def plugins(self) -> list[Plugin]:
        """List of all loaded plugins."""
        return list(self._plugins)

    @property
    def analyzed(self) -> bool:
        """Whether analysis has been run at least once."""
        return self._analyzed

    # ═════════════════════════════════════════════════════════════════
    #  Analysis pipeline
    # ═════════════════════════════════════════════════════════════════

    def analyze_all(self) -> dict[str, Any]:
        """Run the full analysis pipeline.

        Steps:
        1. Notify ``on_analyze_start`` plugins
        2. Run ELF → dispatch → names → push fns
        3. Analyze every ``_bist_*`` function
        4. Auto-detect patterns and register them
        5. Collect unknown-function flags
        6. Build report
        7. Notify ``on_analyze_end`` plugins

        Returns the report dict.
        """
        # 1. Start hooks
        for plugin in self._plugins:
            try:
                plugin.on_analyze_start(self)
            except Exception as e:
                self._log_plugin_error(plugin, "on_analyze_start", e)
        for hook in _ANALYZE_HOOKS:
            try:
                hook(self, "_pipeline_start", {})
            except Exception:
                pass

        # 2. Core analysis
        if not self.binary._analyzed:
            self.binary.analyze()
        else:
            # If loaded from cache, ensure ELF is still available
            if self.binary._elf is None:
                self.binary._elf = ELFReader(self.binary.path)
                self.binary._elf._parse()

        # 3. Analyze every _bist_ function
        function_results: dict[str, dict] = {}
        unclassified: list[str] = []
        for name in sorted(self.binary.symbols):
            if not name.startswith("_bist_") or name == "_bist_store":
                continue
            result = self.analyze_function(name)
            function_results[name] = result
            if result.get("unclassified"):
                unclassified.append(name)

        # 4. Auto-detect patterns
        detected = self._auto_detect_patterns(function_results)

        # 5. Build report
        report = self._build_report(function_results, unclassified, detected)

        # 6. End hooks
        for plugin in self._plugins:
            try:
                plugin.on_analyze_end(self, report)
            except Exception as e:
                self._log_plugin_error(plugin, "on_analyze_end", e)

        self._analyzed = True
        self._last_report = report
        return report

    def analyze_function(self, name: str) -> dict[str, Any]:
        """Run all analysis passes on one dispatch function.

        Returns a merged dict with all analysis results, and flags
        the function as *unclassified* if no matching protocol pattern
        was found.
        """
        result: dict[str, Any] = {
            "name": name,
            "vaddr": self.binary.symbols.get(name),
        }

        # Full protocol analysis
        proto = self.binary.analyze_full_protocol(name)
        result.update(proto)

        # Entry points
        try:
            eps = self.binary.trace_entry_points(name)
            if eps:
                result["entry_candidates"] = eps
        except Exception:
            pass

        # Error codes
        if result.get("vaddr"):
            try:
                ecs = self.binary.trace_error_codes(result["vaddr"])
                if ecs:
                    result["error_codes_found"] = ecs
            except Exception:
                pass

        # Run plugin analysis hooks
        for plugin in self._plugins:
            try:
                plugin.on_analyze_function(self, name, result)
            except Exception as e:
                self._log_plugin_error(plugin, f"on_analyze_function({name})", e)
        for hook in _ANALYZE_HOOKS:
            try:
                hook(self, name, result)
            except Exception:
                pass

        # Check if protocol matches a known pattern
        result["unclassified"] = self._is_unclassified(result)
        return result

    def _is_unclassified(self, result: dict) -> bool:
        """Check if *result* represents an unknown/unclassified function.

        A function is unclassified if:
        - Its protocol type is "unknown" or "no_stack_args"
        - No registered pattern covers it
        - Auto-detection couldn't determine its role
        """
        pt = result.get("protocol_type", "unknown")
        if pt not in ("unknown", "no_stack_args"):
            return False
        # Check if any registry entry describes this function
        name = result.get("name", "")
        return self.registry.lookup(name) is None

    def _auto_detect_patterns(self, function_results: dict[str, dict]
                              ) -> list[dict[str, Any]]:
        """Scan analysis results for new patterns and register them.

        Returns list of dicts describing newly detected patterns.
        """
        detected: list[dict[str, Any]] = []
        sha256 = self.binary.sha256

        for name, result in function_results.items():
            pt = result.get("protocol_type", "")
            if pt and pt != "unknown":
                # Register protocol pattern if not already known
                existing = self.registry.lookup(name)
                if existing is None or existing.source != "hardcoded":
                    self.registry.register_detected(
                        name=name,
                        data={"protocol_type": pt,
                              "dispatch_index": result.get("dispatch_index"),
                              "uses_push_stack": result.get("uses_push_stack"), },
                        sha256=sha256,
                        pattern_type="protocol",
                        description=f"Auto-detected protocol for {name}",
                        tags=["auto_detected", "protocol"],
                    )
                    detected.append({
                        "name": name,
                        "type": "protocol",
                        "protocol": pt,
                    })

            # Entry points
            eps = result.get("entry_candidates", [])
            if len(eps) > 1:
                ep_name = f"{name}_entry_points"
                if self.registry.lookup(ep_name) is None:
                    self.registry.register_detected(
                        name=ep_name,
                        data={"function": name, "entry_points": eps},
                        sha256=sha256,
                        pattern_type="entry_point",
                        description=f"Auto-detected {len(eps)} entry points for {name}",
                        tags=["auto_detected", "entry_point"],
                    )
                    detected.append({
                        "name": ep_name,
                        "type": "entry_point",
                        "count": len(eps),
                    })

        return detected

    def _build_report(self, function_results: dict[str, dict],
                      unclassified: list[str],
                      detected: list[dict]) -> dict[str, Any]:
        """Assemble the comprehensive analysis report dict."""
        return {
            "binary": {
                "path": self.binary.path,
                "sha256": self.binary.sha256[:16],
                "arch": self.binary.arch,
                "format": self.binary.format,
                "dispatch_count": self.binary.dispatch_count,
                "symbol_count": len(self.binary.symbols),
            },
            "analysis": {
                "timestamp": time.time(),
                "functions_analyzed": len(function_results),
                "unclassified_count": len(unclassified),
                "patterns_detected": len(detected),
            },
            "functions": function_results,
            "unclassified": unclassified,
            "new_patterns": detected,
            "registry_stats": self.registry.stats(),
            "plugins": [
                {"name": p.name, "version": p.version,
                 "description": p.description}
                for p in self._plugins
            ],
        }

    # ═════════════════════════════════════════════════════════════════
    #  Reporting
    # ═════════════════════════════════════════════════════════════════

    def report(self, format: str = "json") -> str:
        """Generate a formatted report.

        Parameters
        ----------
        format : str
            ``"json"`` or ``"markdown"``.
        """
        if not self._analyzed:
            return "(not analyzed — call .analyze_all() first)"
        report_data = dict(self._last_report)

        # Run report-generation hooks
        for plugin in self._plugins:
            try:
                plugin.on_report_generate(self, report_data)
            except Exception as e:
                self._log_plugin_error(plugin, "on_report_generate", e)
        for hook in _REPORT_HOOKS:
            try:
                hook(self, report_data)
            except Exception:
                pass

        if format == "markdown":
            return self._format_markdown(report_data)
        return json.dumps(report_data, indent=2, default=str)

    def _format_markdown(self, report: dict) -> str:
        """Format report as markdown."""
        lines = []
        binary = report.get("binary", {})
        lines.append(f"# Analysis Report: {binary.get('path', '?')}")
        lines.append("")
        lines.append(f"- **SHA256**: `{binary.get('sha256', '?')}`")
        lines.append(f"- **Arch**: {binary.get('arch', '?')}")
        lines.append(f"- **Format**: {binary.get('format', '?')}")
        lines.append(f"- **Dispatch table**: {binary.get('dispatch_count', 0)} entries")
        lines.append(f"- **Symbols**: {binary.get('symbol_count', 0)}")
        lines.append("")

        stats = report.get("analysis", {})
        lines.append("## Analysis Summary")
        lines.append("")
        lines.append(f"- Functions analyzed: {stats.get('functions_analyzed', 0)}")
        lines.append(f"- Unclassified: {stats.get('unclassified_count', 0)}")
        lines.append(f"- New patterns detected: {stats.get('patterns_detected', 0)}")
        lines.append("")

        unclassified = report.get("unclassified", [])
        if unclassified:
            lines.append("## Unclassified Functions")
            lines.append("")
            lines.append("These functions did not match any known protocol pattern:")
            lines.append("")
            for name in unclassified[:20]:
                lines.append(f"- `{name}`")
            if len(unclassified) > 20:
                lines.append(f"- ... and {len(unclassified) - 20} more")
            lines.append("")

        new_patterns = report.get("new_patterns", [])
        if new_patterns:
            lines.append("## Newly Detected Patterns")
            lines.append("")
            for p in new_patterns[:20]:
                lines.append(f"- `{p['name']}` ({p['type']})")
            if len(new_patterns) > 20:
                lines.append(f"- ... and {len(new_patterns) - 20} more")
            lines.append("")

        # Protocol summary table
        lines.append("## Protocol Summary")
        lines.append("")
        lines.append("| Function | Idx | Type | Push+Stack | Entry Pts |")
        lines.append("|----------|-----|------|------------|-----------|")
        functions = report.get("functions", {})
        for name in sorted(functions):
            r = functions[name]
            di = str(r.get("dispatch_index", "?"))
            pt = (r.get("protocol_type", "?") or "?")[:20]
            ps = "✓" if r.get("uses_push_stack") else "✗"
            ec = str(len(r.get("entry_candidates", [])))
            lines.append(f"| `{name}` | {di} | {pt} | {ps} | {ec} |")
        lines.append("")

        # Plugins
        plugins = report.get("plugins", [])
        lines.append("## Plugins Loaded")
        lines.append("")
        for p in plugins:
            lines.append(f"- **{p['name']}** v{p['version']}: {p.get('description', '')}")
        lines.append("")

        # Registry stats
        rs = report.get("registry_stats", {})
        lines.append("## Registry Stats")
        lines.append("")
        lines.append(f"- Hardcoded defaults: {rs.get('hardcoded', 0)}")
        lines.append(f"- Auto-detected: {rs.get('auto_detected', 0)}")
        lines.append(f"- User-added: {rs.get('user_added', 0)}")
        lines.append(f"- Total: {rs.get('total', 0)}")
        lines.append("")

        return "\n".join(lines)

    def generate_report(self, output_dir: str = ".") -> dict[str, str]:
        """Generate full documentation in *output_dir*.

        Produces:
        - ``ANALYSIS_REPORT.md``
        - ``ARCHITECTURE.md`` (living knowledge doc)
        - ``docs/fn/FUNCTION_NAME.md`` per-function stubs

        Returns dict mapping filenames to paths written.
        """
        if not self._analyzed:
            raise RuntimeError("Call analyze_all() before generate_report()")

        os.makedirs(output_dir, exist_ok=True)
        written: dict[str, str] = {}

        # 1. ANALYSIS_REPORT.md
        report_md = self.report(format="markdown")
        report_path = os.path.join(output_dir, "ANALYSIS_REPORT.md")
        with open(report_path, "w") as f:
            f.write(report_md)
        written["ANALYSIS_REPORT.md"] = report_path

        # 2. ARCHITECTURE.md (living knowledge document)
        arch_md = self._generate_architecture_md()
        arch_path = os.path.join(output_dir, "ARCHITECTURE.md")
        with open(arch_path, "w") as f:
            f.write(arch_md)
        written["ARCHITECTURE.md"] = arch_path

        # 3. Per-function docs
        fn_dir = os.path.join(output_dir, "docs", "fn")
        os.makedirs(fn_dir, exist_ok=True)
        functions = self._last_report.get("functions", {})
        for name, result in sorted(functions.items()):
            fn_md = self._generate_function_doc(name, result)
            fn_path = os.path.join(fn_dir, f"{name}.md")
            with open(fn_path, "w") as f:
                f.write(fn_md)
            written[f"docs/fn/{name}.md"] = fn_path

        return written

    def _generate_architecture_md(self) -> str:
        """Generate the living ARCHITECTURE.md from registry + analysis."""
        lines = []
        lines.append("# Stata Binary Architecture (Living Document)")
        lines.append("")
        lines.append(f"*Generated from analysis of: `{self.binary.path}`*")
        lines.append(f"*SHA256: `{self.binary.sha256[:16]}`*")
        lines.append("")

        # Address patterns
        addr_patterns = self.registry.lookup_by_type("address")
        if addr_patterns:
            lines.append("## Key Memory Addresses")
            lines.append("")
            lines.append("| Symbol | VAddr | Purpose |")
            lines.append("|--------|-------|---------|")
            for p in addr_patterns:
                vaddr = p.data.get("vaddr", 0)
                purpose = p.data.get("purpose", p.description)
                lines.append(f"| `{p.name}` | `0x{vaddr:x}` | {purpose} |")
            lines.append("")

        # Protocol patterns
        proto_patterns = self.registry.lookup_by_type("protocol")
        if proto_patterns:
            lines.append("## Protocol Patterns")
            lines.append("")
            for p in proto_patterns:
                lines.append(f"### {p.name}")
                lines.append("")
                lines.append(p.description)
                lines.append("")
                # ASCII diagram for known protocol types
                ptype = p.data.get("type", "")
                if ptype == "push_stack":
                    lines.append("```")
                    lines.append("Push+Stack Protocol:")
                    lines.append("  1. _pushdbl/_pushint/_pushstr alloc tsmat, update ARG_PTR")
                    lines.append("  2. Implementation indexes backward from ARG_PTR")
                    lines.append("  3. Reads tsmat[0] for double or GSO string pointer")
                    lines.append("  4. Pool-header check: tsmat[-0x94] == 0x2b")
                    lines.append("```")
                elif ptype == "sp_reset":
                    lines.append("```")
                    lines.append("SP-Reset Protocol:")
                    lines.append("  1. Thunk writes descriptor address to SP_global")
                    lines.append("  2. Implementation reads from global C struct")
                    lines.append("  3. No push functions needed")
                    lines.append("  4. Always 0-arg or 1-arg scalar return")
                    lines.append("```")
                elif ptype == "internal_global":
                    lines.append("```")
                    lines.append("Internal-Global Protocol:")
                    lines.append("  1. Caller goes through type-checking thunk first")
                    lines.append("  2. Implementation reads from Stata internal state")
                    lines.append("  3. Not usable from external code directly")
                    lines.append("```")
                lines.append("")

        # Known function patterns
        fn_patterns = self.registry.lookup_by_type("convention")
        if fn_patterns:
            lines.append("## Key Conventions")
            lines.append("")
            for p in fn_patterns:
                lines.append(f"### {p.name}")
                lines.append("")
                lines.append(p.description)
                lines.append("")

        # Error codes
        error_patterns = self.registry.lookup_by_type("error_code")
        if error_patterns:
            lines.append("## Error Code Map")
            lines.append("")
            lines.append("| Code | Hex | Meaning |")
            lines.append("|------|-----|---------|")
            for p in sorted(error_patterns, key=lambda x: x.data.get("code", 0)):
                code = p.data.get("code", 0)
                hex_str = p.data.get("hex", "")
                meaning = p.data.get("meaning", p.description)
                lines.append(f"| {code} | 0x{hex_str:x} | {meaning} |")
            lines.append("")

        return "\n".join(lines)

    def _generate_function_doc(self, name: str, result: dict) -> str:
        """Generate per-function documentation."""
        lines = []
        lines.append(f"# {name}")
        lines.append("")
        lines.append(f"- **VAddr**: `0x{result.get('vaddr', 0):x}`")
        lines.append(f"- **Dispatch index**: {result.get('dispatch_index', '?')}")
        lines.append(f"- **Protocol type**: {result.get('protocol_type', '?')}")
        lines.append(f"- **Uses push+stack**: {result.get('uses_push_stack', '?')}")
        lines.append("")

        # Entry points
        eps = result.get("entry_candidates", [])
        if eps:
            lines.append("## Entry Points")
            lines.append("")
            lines.append("| VAddr | Notes |")
            lines.append("|-------|-------|")
            for ep in eps:
                vad = ep.get("vaddr", 0)
                lines.append(f"| `0x{vad:x}` | {ep.get('notes', '')} |")
            lines.append("")

        # Error codes
        ecs = result.get("error_codes", []) or result.get("error_codes_found", [])
        if ecs:
            lines.append("## Error Codes")
            lines.append("")
            lines.append("| Address | Code | Meaning |")
            lines.append("|---------|------|---------|")
            for ec in ecs[:10]:
                vad = ec.get("vaddr", ec.get("address", 0))
                code = ec.get("checks", ec.get("code", 0))
                meaning = ec.get("meaning", "")
                lines.append(f"| `0x{vad:x}` | {code} | {meaning} |")
            lines.append("")

        # Push-str calls
        ps_calls = result.get("pushstr_calls", [])
        if ps_calls:
            lines.append("## Push-String Calls")
            lines.append("")
            for pc in ps_calls[:5]:
                vad = pc.get("vaddr", 0)
                lines.append(f"- `_pushstr` call at `0x{vad:x}`")
            lines.append("")

        return "\n".join(lines)

    # ═════════════════════════════════════════════════════════════════
    #  Diff
    # ═════════════════════════════════════════════════════════════════

    def diff(self, other: "Framework") -> dict[str, Any]:
        """Compare this analysis with another binary version.

        Returns dict with sections: ``new_functions``, ``removed_functions``,
        ``changed_protocols``, ``new_patterns``, ``registry_diff``.
        """
        if not self._analyzed or not other._analyzed:
            # Auto-analyze if needed
            if not self._analyzed:
                self.analyze_all()
            if not other._analyzed:
                other.analyze_all()

        my_fns = self._last_report.get("functions", {})
        their_fns = other._last_report.get("functions", {})

        my_names = set(my_fns)
        their_names = set(their_fns)

        new_fns = sorted(their_names - my_names)
        removed_fns = sorted(my_names - their_names)

        changed_protocols = []
        for name in sorted(my_names & their_names):
            my_pt = my_fns[name].get("protocol_type")
            their_pt = their_fns[name].get("protocol_type")
            if my_pt != their_pt:
                changed_protocols.append({
                    "name": name,
                    "old": my_pt,
                    "new": their_pt,
                })

        return {
            "binary_diff": {
                "this": self.binary.sha256[:16],
                "other": other.binary.sha256[:16],
            },
            "new_functions": new_fns,
            "removed_functions": removed_fns,
            "changed_protocols": changed_protocols,
            "new_patterns": self._auto_detect_patterns(their_fns),
            "registry_diff": self._registry_diff(other),
        }

    def _registry_diff(self, other: "Framework") -> dict[str, list[str]]:
        """Compare registries."""
        my_names = {e.name for e in self.registry.list()}
        their_names = {e.name for e in other.registry.list()}
        return {
            "added": sorted(their_names - my_names),
            "removed": sorted(my_names - their_names),
            "common": sorted(my_names & their_names),
        }

    # ═════════════════════════════════════════════════════════════════
    #  API doc generation
    # ═════════════════════════════════════════════════════════════════

    def generate_api_docs(self, output_dir: str = "docs/api") -> str:
        """Generate API reference docs from pystata-analyzer source docstrings.

        Returns the path to the generated ``index.md``.
        """
        import pystata_analyzer as pa
        pkg_dir = os.path.dirname(pa.__file__)
        os.makedirs(output_dir, exist_ok=True)

        index_lines = [
            "# pystata-analyzer API Reference",
            "",
            f"*Generated from `{pkg_dir}`*",
            "",
            "## Modules",
            "",
        ]

        for fname in sorted(os.listdir(pkg_dir)):
            if not fname.endswith(".py") or fname == "__pycache__":
                continue
            mod_name = f"pystata_analyzer.{fname[:-3]}"
            fpath = os.path.join(pkg_dir, fname)
            doc_path = os.path.join(output_dir, f"{fname[:-3]}.md")

            with open(fpath) as f:
                content = f.read()
            import ast
            try:
                tree = ast.parse(content)
            except SyntaxError:
                continue

            mod_doc = ast.get_docstring(tree) or ""

            lines = [
                f"# {mod_name}",
                "",
                mod_doc,
                "",
                "## Classes and Functions",
                "",
            ]

            for node in ast.walk(tree):
                if not isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                doc = ast.get_docstring(node)
                if not doc:
                    continue
                if isinstance(node, ast.ClassDef):
                    lines.append(f"### `class {node.name}`")
                    lines.append("")
                    lines.append(doc)
                    lines.append("")
                elif isinstance(node, ast.FunctionDef):
                    lines.append(f"### `{node.name}()`")
                    lines.append("")
                    lines.append(doc)
                    lines.append("")

            with open(doc_path, "w") as f:
                f.write("\n".join(lines))

            index_lines.append(f"- [{mod_name}]({fname[:-3]}.md) — {mod_doc[:80]}")

        index_path = os.path.join(output_dir, "index.md")
        with open(index_path, "w") as f:
            f.write("\n".join(index_lines))

        return index_path

    # ═════════════════════════════════════════════════════════════════
    #  Internal helpers
    # ═════════════════════════════════════════════════════════════════

    @staticmethod
    def _log_plugin_error(plugin: Plugin, hook: str,
                          exception: Exception) -> None:
        """Log a plugin error (does not crash the pipeline)."""
        import sys
        print(f"[framework] Plugin {plugin.name} errored in {hook}: "
              f"{exception}", file=sys.stderr)

    def __repr__(self) -> str:
        return (f"<Framework binary={self.binary_path} "
                f"analyzed={self._analyzed} "
                f"plugins={len(self._plugins)}>")
