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
from datetime import date, datetime
from typing import Any, Optional

from pystata_analyzer import StataBinary, ELFReader
from pystata_analyzer.registry import PatternRegistry, PatternEntry
from pystata_analyzer.plugin import (
    Plugin, BUILTIN_PLUGINS, discover_plugins, resolve_dependencies,
    _ANALYZE_HOOKS, _REPORT_HOOKS,
)

# Retain this many dated doc sets (older ones are pruned)
DEFAULT_RETENTION = 10


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
        self._plugin_dir = plugin_dir

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
        self._prev_report: dict[str, Any] = {}  # for change tracking

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
    #  Plugin hot-reloading
    # ═════════════════════════════════════════════════════════════════

    def register_plugin(self, plugin: Plugin) -> None:
        """Register a new plugin at runtime and run its ``on_analyze_start``
        hook (if analysis has already been run).

        The plugin is added to the internal list and dependency resolution
        is re-run.
        """
        if plugin.name in {p.name for p in self._plugins}:
            raise ValueError(f"Plugin {plugin.name!r} is already registered")
        self._plugins.append(plugin)
        try:
            self._plugins = resolve_dependencies(self._plugins)
        except ValueError as e:
            # Rollback
            self._plugins = [p for p in self._plugins if p.name != plugin.name]
            raise ValueError(f"Cannot register {plugin.name!r}: {e}") from e
        # If analysis has already run, fire the start hook
        if self._analyzed:
            try:
                plugin.on_analyze_start(self)
            except Exception as e:
                self._log_plugin_error(plugin, "on_analyze_start", e)
            # Re-run function hooks on existing report
            for name, result in self._last_report.get("functions", {}).items():
                try:
                    plugin.on_analyze_function(self, name, result)
                except Exception as e:
                    self._log_plugin_error(plugin,
                                           f"on_analyze_function({name})", e)
            try:
                plugin.on_analyze_end(self, self._last_report)
            except Exception as e:
                self._log_plugin_error(plugin, "on_analyze_end", e)

    def unregister_plugin(self, name: str) -> None:
        """Remove a plugin by name from the framework.

        Does nothing if the plugin is not registered.  Re-runs dependency
        resolution after removal.
        """
        self._plugins = [p for p in self._plugins if p.name != name]
        try:
            self._plugins = resolve_dependencies(self._plugins)
        except ValueError:
            # Even if resolution fails, the plugin is removed
            pass

    def reload_plugins(self) -> list[str]:
        """Re-discover plugins from ``plugin_dir`` and hot-swap.

        Keeps the binary and registry; re-runs all analysis hooks on the
        existing report.  Returns list of plugin names that were updated.
        """
        updated: list[str] = []
        if not hasattr(self, '_plugin_dir') or not self._plugin_dir:
            return updated

        # Discover new plugins from dir
        discovered = discover_plugins(self._plugin_dir)
        # Remove old discovered plugins (those not built-in or explicitly added)
        self._plugins = [
            p for p in self._plugins
            if p.name in BUILTIN_PLUGINS
            or hasattr(p, '_explicitly_added')
        ]
        # Add newly discovered
        for plugin in discovered:
            if plugin.name not in {p.name for p in self._plugins}:
                self._plugins.append(plugin)
                updated.append(plugin.name)

        try:
            self._plugins = resolve_dependencies(self._plugins)
        except ValueError as e:
            self._log_plugin_error(None, "reload_plugins", e)

        # Re-run hooks if analysis already done
        if self._analyzed and updated:
            for plugin in self._plugins:
                if plugin.name in updated:
                    try:
                        plugin.on_analyze_start(self)
                    except Exception as e:
                        self._log_plugin_error(plugin, "on_analyze_start", e)
            for name, result in self._last_report.get("functions", {}).items():
                for plugin in self._plugins:
                    if plugin.name in updated:
                        try:
                            plugin.on_analyze_function(self, name, result)
                        except Exception:
                            pass
            for plugin in self._plugins:
                if plugin.name in updated:
                    try:
                        plugin.on_analyze_end(self, self._last_report)
                    except Exception:
                        pass

        return updated

    def set_plugin_dir(self, path: str) -> list[str]:
        """Set the plugin directory and trigger a reload.

        Returns list of newly loaded plugin names.
        """
        self._plugin_dir = path
        return self.reload_plugins()

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
        self._prev_report = dict(self._last_report)
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

        # Push calls (all types)
        if result.get("vaddr"):
            try:
                pcs = self.binary.trace_all_push_calls(result["vaddr"])
                if pcs:
                    result["push_calls"] = pcs
            except Exception:
                pass

        # Pool checks
        if result.get("vaddr"):
            try:
                pcs = self.binary.trace_pool_checks(result["vaddr"])
                if pcs:
                    result["pool_checks"] = pcs
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
        name = result.get("name", "")
        return self.registry.lookup(name) is None

    def _auto_detect_patterns(self, function_results: dict[str, dict]
                              ) -> list[dict[str, Any]]:
        """Scan analysis results for new patterns and register them."""
        detected: list[dict[str, Any]] = []
        sha256 = self.binary.sha256

        for name, result in function_results.items():
            pt = result.get("protocol_type", "")
            if pt and pt != "unknown":
                existing = self.registry.lookup(name)
                if existing is None or existing.source != "hardcoded":
                    self.registry.register_detected(
                        name=name,
                        data={"protocol_type": pt,
                              "dispatch_index": result.get("dispatch_index"),
                              "uses_push_stack": result.get("uses_push_stack")},
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

        lines.append("## Protocol Summary")
        lines.append("")
        lines.append("| Function | Idx | Type | Push+Stack | Entry Pts | Error Codes | Push Calls |")
        lines.append("|----------|-----|------|------------|-----------|-------------|------------|")
        functions = report.get("functions", {})
        for name in sorted(functions):
            r = functions[name]
            di = str(r.get("dispatch_index", "?"))
            pt = (r.get("protocol_type", "?") or "?")[:20]
            ps = "✓" if r.get("uses_push_stack") else "✗"
            ec = str(len(r.get("entry_candidates", [])))
            errs = str(len(r.get("error_codes", []) or r.get("error_codes_found", [])))
            pc = str(len(r.get("push_calls", [])))
            lines.append(f"| `{name}` | {di} | {pt} | {ps} | {ec} | {errs} | {pc} |")
        lines.append("")

        # ── Cross-Reference Index ──
        xref = self._build_cross_reference_index(report.get("functions", {}))
        shared_entries = xref.get("shared_dispatch_entries", {})
        if shared_entries:
            lines.append("## Cross-Reference Index")
            lines.append("")
            lines.append("### Shared Dispatch Entry Groups")
            lines.append("")
            lines.append("| VAddr | Functions |")
            lines.append("|-------|-----------|")
            for vaddr_hex, names in sorted(shared_entries.items()):
                lines.append(f"| `{vaddr_hex}` | {', '.join(f'`{n}`' for n in names)} |")
            lines.append("")

        call_graph = xref.get("call_graph", {})
        if call_graph:
            lines.append("### Call Graph (Push Function Usage)")
            lines.append("")
            lines.append("| Function | Push Function Calls |")
            lines.append("|----------|--------------------|")
            for fn, targets in sorted(call_graph.items()):
                lines.append(f"| `{fn}` | {', '.join(f'`{t}`' for t in targets)} |")
            lines.append("")

        by_protocol = xref.get("by_protocol_type", {})
        if by_protocol:
            lines.append("### Protocol Type Groups")
            lines.append("")
            for pt, names in sorted(by_protocol.items()):
                lines.append(f"- **{pt}** ({len(names)} functions): "
                             f"{', '.join(f'`{n}`' for n in names[:5])}")
                if len(names) > 5:
                    lines.append(f"  ... and {len(names) - 5} more")
            lines.append("")

        plugins = report.get("plugins", [])
        lines.append("## Plugins Loaded")
        lines.append("")
        for p in plugins:
            lines.append(f"- **{p['name']}** v{p['version']}: {p.get('description', '')}")
        lines.append("")

        rs = report.get("registry_stats", {})
        lines.append("## Registry Stats")
        lines.append("")
        lines.append(f"- Hardcoded defaults: {rs.get('hardcoded', 0)}")
        lines.append(f"- Auto-detected: {rs.get('auto_detected', 0)}")
        lines.append(f"- User-added: {rs.get('user_added', 0)}")
        lines.append(f"- Total: {rs.get('total', 0)}")
        lines.append("")

        return "\n".join(lines)

    # ═════════════════════════════════════════════════════════════════
    #  Documentation generation (versioned output)
    # ═════════════════════════════════════════════════════════════════

    def generate_report(self, output_dir: str = ".") -> dict[str, str]:
        """Generate full documentation in a versioned output directory.

        Produces:
        - ``<date>/ANALYSIS_REPORT.md``
        - ``<date>/ARCHITECTURE.md`` (living knowledge doc)
        - ``<date>/docs/fn/FUNCTION_NAME.md`` per-function docs
        - ``<date>/agent-knowledge.json`` (structured agent knowledge)
        - ``<date>/CHANGELOG.md`` (change tracking)
        - ``<output>/LATEST`` symlink to the most recent doc set
        - ``<output>/ARCHITECTURE.md`` (cross-version index)

        Parameters
        ----------
        output_dir : str
            Base output directory (versioned subdirectory is created inside).

        Returns
        -------
        dict[str, str]
            Mapping of logical filenames to absolute paths written.
        """
        if not self._analyzed:
            raise RuntimeError("Call analyze_all() before generate_report()")

        # Load previous knowledge for cross-run changelog
        prev_knowledge = self._load_previous_knowledge(output_dir)
        if prev_knowledge:
            self._prev_report = self._knowledge_to_report(prev_knowledge)

        today_str = date.today().isoformat()
        version_dir = os.path.join(output_dir, today_str)
        os.makedirs(version_dir, exist_ok=True)
        written: dict[str, str] = {}

        # 1. ANALYSIS_REPORT.md
        report_md = self.report(format="markdown")
        report_path = os.path.join(version_dir, "ANALYSIS_REPORT.md")
        with open(report_path, "w") as f:
            f.write(report_md)
        written["ANALYSIS_REPORT.md"] = report_path

        # 2. ARCHITECTURE.md (living knowledge document)
        arch_md = self._generate_architecture_md()
        arch_path = os.path.join(version_dir, "ARCHITECTURE.md")
        with open(arch_path, "w") as f:
            f.write(arch_md)
        written["ARCHITECTURE.md"] = arch_path

        # 3. Per-function docs
        fn_dir = os.path.join(version_dir, "docs", "fn")
        os.makedirs(fn_dir, exist_ok=True)
        functions = self._last_report.get("functions", {})
        for name, result in sorted(functions.items()):
            fn_md = self._generate_function_doc(name, result)
            fn_path = os.path.join(fn_dir, f"{name}.md")
            with open(fn_path, "w") as f:
                f.write(fn_md)
            written[f"docs/fn/{name}.md"] = fn_path

        # 4. Agent knowledge JSON
        knowledge = self._generate_agent_knowledge_json(functions)
        kb_path = os.path.join(version_dir, "agent-knowledge.json")
        with open(kb_path, "w") as f:
            json.dump(knowledge, f, indent=2, default=str)
        written["agent-knowledge.json"] = kb_path

        # 5. Change tracking
        changelog = self._compute_changelog()
        if changelog:
            cl_path = os.path.join(version_dir, "CHANGELOG.md")
            cl_md = self._format_changelog(changelog)
            with open(cl_path, "w") as f:
                f.write(cl_md)
            written["CHANGELOG.md"] = cl_path

        # 6. Update LATEST symlink
        latest_link = os.path.join(output_dir, "LATEST")
        if os.path.islink(latest_link) or os.path.exists(latest_link):
            os.remove(latest_link)
        try:
            rel = os.path.relpath(version_dir, output_dir)
            os.symlink(rel, latest_link)
        except OSError:
            pass

        # 7. Prune old doc sets
        self._prune_old(output_dir, keep=DEFAULT_RETENTION)

        # 8. Update root ARCHITECTURE.md (cross-version index)
        arch_root_path = os.path.join(output_dir, "ARCHITECTURE.md")
        with open(arch_root_path, "w") as f:
            f.write(self._generate_root_architecture_md(version_dir))
        written["ARCHITECTURE.md (root)"] = arch_root_path

        return written

    def _generate_root_architecture_md(self, latest_version_dir: str) -> str:
        """Generate the root ARCHITECTURE.md that points to versioned sets."""
        lines = []
        lines.append("# Stata Binary Architecture (Multi-Version Index)")
        lines.append("")
        lines.append(f"*Latest analysis: `{os.path.basename(latest_version_dir)}`*")
        lines.append("")
        lines.append("This document indexes all versioned analysis documentation sets.")
        lines.append("Each dated directory contains a complete snapshot of the binary")
        lines.append("analysis, including per-function docs and agent knowledge.")
        lines.append("")
        lines.append("## Versioned Doc Sets")
        lines.append("")
        parent = os.path.dirname(latest_version_dir) or "."
        try:
            entries = sorted(os.listdir(parent))
            for entry in reversed(entries):
                entry_path = os.path.join(parent, entry)
                if os.path.isdir(entry_path) and entry[0].isdigit():
                    label = "← LATEST" if entry == os.path.basename(latest_version_dir) else ""
                    lines.append(f"- `{entry}/` {label}")
        except OSError:
            pass
        lines.append("")
        lines.append("*Generated by pystata-analyzer Framework*")
        return "\n".join(lines)

    def _compute_changelog(self) -> dict[str, Any]:
        """Compare current analysis with previous run to produce changelog."""
        if not self._prev_report:
            return {}
        prev_fns = self._prev_report.get("functions", {})
        curr_fns = self._last_report.get("functions", {})

        prev_names = set(prev_fns)
        curr_names = set(curr_fns)

        added = sorted(curr_names - prev_names)
        removed = sorted(prev_names - curr_names)

        changed: list[dict] = []
        for name in sorted(curr_names & prev_names):
            prev_pt = prev_fns[name].get("protocol_type")
            curr_pt = curr_fns[name].get("protocol_type")
            prev_ec = len(prev_fns[name].get("error_codes", []) or
                          prev_fns[name].get("error_codes_found", []))
            curr_ec = len(curr_fns[name].get("error_codes", []) or
                          curr_fns[name].get("error_codes_found", []))
            prev_push = len(prev_fns[name].get("push_calls", []))
            curr_push = len(curr_fns[name].get("push_calls", []))
            changes = {}
            if prev_pt != curr_pt:
                changes["protocol_type"] = {"old": prev_pt, "new": curr_pt}
            if prev_ec != curr_ec:
                changes["error_code_count"] = {"old": prev_ec, "new": curr_ec}
            if prev_push != curr_push:
                changes["push_call_count"] = {"old": prev_push, "new": curr_push}
            if changes:
                changed.append({"name": name, "changes": changes})

        return {
            "timestamp": time.time(),
            "binary_sha256": self.binary.sha256[:16],
            "added_functions": added,
            "removed_functions": removed,
            "changed_functions": changed,
            "total_changes": len(added) + len(removed) + len(changed),
        }

    def _format_changelog(self, changelog: dict) -> str:
        """Format changelog as markdown."""
        lines = []
        lines.append("# Changelog")
        lines.append("")
        lines.append(f"*Binary: `{self.binary.path}`*")
        dt = datetime.fromtimestamp(changelog.get("timestamp", time.time()))
        lines.append(f"*Analysis date: {dt.isoformat()}*")
        lines.append(f"*SHA256: `{changelog.get('binary_sha256', '?')}`*")
        lines.append("")

        added = changelog.get("added_functions", [])
        removed = changelog.get("removed_functions", [])
        changed = changelog.get("changed_functions", [])

        if added:
            lines.append("## Added Functions")
            lines.append("")
            for name in added:
                lines.append(f"- `{name}`")
            lines.append("")

        if removed:
            lines.append("## Removed Functions")
            lines.append("")
            for name in removed:
                lines.append(f"- `{name}`")
            lines.append("")

        if changed:
            lines.append("## Changed Functions")
            lines.append("")
            lines.append("| Function | Change | Old | New |")
            lines.append("|----------|--------|-----|-----|")
            for c in changed:
                name = c["name"]
                for attr, vals in c["changes"].items():
                    lines.append(f"| `{name}` | {attr} | `{vals['old']}` | `{vals['new']}` |")
            lines.append("")

        if not added and not removed and not changed:
            lines.append("_No changes detected since previous analysis._")
            lines.append("")

        lines.append(f"**Total changes**: {changelog.get('total_changes', 0)}")
        lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _prune_old(output_dir: str, keep: int = DEFAULT_RETENTION) -> None:
        """Remove dated doc sets beyond *keep* most recent."""
        try:
            entries = sorted([
                e for e in os.listdir(output_dir)
                if os.path.isdir(os.path.join(output_dir, e))
                and e[0].isdigit()
            ])
        except OSError:
            return
        to_remove = entries[:-keep] if len(entries) > keep else []
        for entry in to_remove:
            import shutil
            shutil.rmtree(os.path.join(output_dir, entry), ignore_errors=True)

    def _load_previous_knowledge(self, output_dir: str
                                 ) -> Optional[dict]:
        """Load the most recent previous ``agent-knowledge.json`` from
        a dated subdirectory of *output_dir*, for cross-run changelog.
        Returns None if no previous knowledge is found."""
        try:
            entries = sorted([
                e for e in os.listdir(output_dir)
                if os.path.isdir(os.path.join(output_dir, e))
                and e[0].isdigit()
            ])
        except OSError:
            return None
        current = date.today().isoformat()
        # Find the most recent dir that is not today's
        for entry in reversed(entries):
            if entry == current:
                continue
            kb_path = os.path.join(output_dir, entry, "agent-knowledge.json")
            if os.path.exists(kb_path):
                try:
                    with open(kb_path) as f:
                        return json.load(f)
                except (json.JSONDecodeError, OSError):
                    pass
        return None

    @staticmethod
    def _knowledge_to_report(knowledge: dict) -> dict:
        """Convert an ``agent-knowledge.json`` dict into a report-like
        dict so that ``_compute_changelog()`` can compare it."""
        fns = {}
        for name, entry in knowledge.get("function_knowledge", {}).items():
            fn = {
                "name": name,
                "vaddr": entry.get("vaddr"),
                "dispatch_index": entry.get("dispatch_index"),
                "protocol_type": entry.get("protocol_type"),
                "unclassified": entry.get("unclassified", True),
                "uses_push_stack": entry.get("uses_push_stack", False),
                "entry_candidates": [
                    {"vaddr": e["vaddr"], "type": e["type"],
                     "push_count": e.get("push_count"),
                     "offset": e.get("offset")}
                    for e in entry.get("entry_points", [])
                ],
                "error_codes": [
                    {"vaddr": e["vaddr"],
                     "error_code": e.get("error_code"),
                     "guard_context": e.get("context", [])}
                    for e in entry.get("error_codes", [])
                ],
                "push_calls": [
                    {"vaddr": p["vaddr"],
                     "push_function": p.get("push_function")}
                    for p in entry.get("push_calls", [])
                ],
            }
            fns[name] = fn
        return {"functions": fns}

    # ═════════════════════════════════════════════════════════════════
    #  Agent knowledge JSON
    # ═════════════════════════════════════════════════════════════════

    def _generate_agent_knowledge_json(self,
                                       functions: dict[str, dict]
                                       ) -> dict[str, Any]:
        """Produce a structured JSON knowledge base for LLM consumption.

        Designed to be parseable without Capstone or pystata-analyzer
        installed — pure data that an agent can ingest quickly.
        """
        xref = self._build_cross_reference_index(functions)

        return {
            "schema_version": 1,
            "generated": datetime.utcnow().isoformat(),
            "binary": {
                "path": self.binary.path,
                "sha256": self.binary.sha256,
                "arch": self.binary.arch,
                "format": self.binary.format,
                "dispatch_count": self.binary.dispatch_count,
                "symbol_count": len(self.binary.symbols),
            },
            "symbols": {
                name: {
                    "vaddr": vaddr,
                    "is_dispatch_function": name.startswith("_bist_"),
                }
                for name, vaddr in self.binary.symbols.items()
            },
            "dispatch_table": {
                "vaddr": self.binary.dispatch_vaddr,
                "count": self.binary.dispatch_count,
            },
            "function_knowledge": {
                name: self._function_knowledge_entry(name, result)
                for name, result in sorted(functions.items())
            },
            "registry": {
                "version": getattr(self.registry, "_version", "1"),
                "hardcoded_patterns": [
                    {
                        "name": e.name,
                        "type": e.pattern_type,
                        "description": e.description,
                        "tags": e.tags,
                        "data": e.data,
                    }
                    for e in self.registry.list(source="hardcoded")
                ],
                "auto_detected_patterns": [
                    {
                        "name": e.name,
                        "type": e.pattern_type,
                        "description": e.description,
                        "tags": e.tags,
                        "data": e.data,
                    }
                    for e in self.registry.list(source="auto_detected")
                ],
            },
            "cross_references": xref,
            "manifest": {
                "version": getattr(self.binary, "_manifest_version", 2),
            },
        }

    def _function_knowledge_entry(self, name: str,
                                  result: dict) -> dict[str, Any]:
        """Build one function entry for the agent knowledge JSON."""
        entry = {
            "vaddr": result.get("vaddr"),
            "dispatch_index": result.get("dispatch_index"),
            "protocol_type": result.get("protocol_type"),
            "unclassified": result.get("unclassified", True),
            "uses_push_stack": result.get("uses_push_stack", False),
        }

        arg_reads = result.get("arg_ptr_reads", [])
        if arg_reads:
            entry["arg_ptr_reads"] = [
                {"vaddr": a["vaddr"], "offset": a.get("offset")}
                for a in arg_reads
            ]

        sp = result.get("sp_global_access", [])
        if sp:
            entry["sp_global_access"] = sp

        eps = result.get("entry_candidates", [])
        if eps:
            entry["entry_points"] = [
                {
                    "vaddr": e.get("vaddr"),
                    "type": e.get("type"),
                    "push_count": e.get("push_count"),
                    "offset": e.get("offset"),
                }
                for e in eps
            ]

        pcs = result.get("push_calls", [])
        if pcs:
            entry["push_calls"] = [
                {
                    "vaddr": p.get("vaddr"),
                    "push_function": p.get("push_function"),
                    "offset": p.get("offset"),
                }
                for p in pcs
            ]

        ecs = result.get("error_codes", []) or result.get("error_codes_found", [])
        if ecs:
            entry["error_codes"] = [
                {
                    "vaddr": e.get("vaddr"),
                    "error_code": e.get("error_code", e.get("code")),
                    "context": (e.get("guard_context", []) or
                                e.get("checks", "")),
                }
                for e in ecs
            ]

        pcs = result.get("pool_checks", [])
        if pcs:
            entry["pool_header_checks"] = [
                {"vaddr": p["vaddr"]} for p in pcs
            ]

        edi = result.get("edi_checks", [])
        if edi:
            entry["edi_checks"] = edi

        reg_entries = self.registry.lookup_by_type("protocol")
        matched_patterns = []
        for re_ in reg_entries:
            d = re_.data or {}
            if d.get("protocol_type") == result.get("protocol_type"):
                matched_patterns.append(re_.name)
        if matched_patterns:
            entry["matched_registry_patterns"] = matched_patterns

        return entry

    def _build_cross_reference_index(self, functions: dict[str, dict]
                                     ) -> dict[str, Any]:
        """Build a cross-reference index from analysis results."""
        by_vaddr: dict[int, list[str]] = {}
        for name, result in functions.items():
            vaddr = result.get("vaddr")
            if vaddr:
                by_vaddr.setdefault(vaddr, []).append(name)

        shared_entries = {
            hex(vaddr): names
            for vaddr, names in by_vaddr.items()
            if len(names) > 1
        }

        call_graph: dict[str, list[str]] = {}
        for name, result in functions.items():
            pcs = result.get("push_calls", [])
            targets = sorted(set(
                p.get("push_function", "")
                for p in pcs
            ))
            if targets:
                call_graph[name] = targets

        by_dispatch: dict[int, list[str]] = {}
        for name, result in functions.items():
            di = result.get("dispatch_index")
            if di is not None:
                by_dispatch.setdefault(di, []).append(name)

        by_protocol: dict[str, list[str]] = {}
        for name, result in functions.items():
            pt = result.get("protocol_type", "unknown")
            by_protocol.setdefault(pt, []).append(name)

        return {
            "shared_dispatch_entries": shared_entries,
            "call_graph": call_graph,
            "by_dispatch_index": {
                str(di): names
                for di, names in sorted(by_dispatch.items())
            },
            "by_protocol_type": by_protocol,
            "total_functions": len(functions),
        }

    # ═════════════════════════════════════════════════════════════════
    #  Per-function documentation (expanded)
    # ═════════════════════════════════════════════════════════════════

    def _generate_function_doc(self, name: str, result: dict) -> str:
        """Generate comprehensive per-function documentation.

        Includes: vaddr/dispatch index, protocol type, basic-block
        disassembly summary, register flow trace, push calls, entry
        points, error code map, pool-header checks, ASCII call-flow
        diagram, and cross-references.
        """
        lines = []
        vaddr = result.get("vaddr", 0)
        di = result.get("dispatch_index", "?")
        pt = result.get("protocol_type", "?")
        unclassified = result.get("unclassified", True)

        lines.append(f"# {name}")
        lines.append("")
        if unclassified:
            lines.append("> ⚠️ **Unclassified** — No known protocol pattern matched.")
            lines.append("")
        lines.append("## Overview")
        lines.append("")
        lines.append("| Field | Value |")
        lines.append("|-------|-------|")
        lines.append(f"| **VAddr** | `0x{vaddr:x}` |")
        lines.append(f"| **Dispatch index** | {di} |")
        lines.append(f"| **Protocol type** | `{pt}` |")
        lines.append(f"| **Uses push+stack** | {'✓' if result.get('uses_push_stack') else '✗'} |")
        lines.append(f"| **Effective name** | {result.get('effective_name', '-')} |")
        lines.append("")

        # ── Shared entry warning ──
        effective = result.get("effective_name")
        if effective:
            lines.append("> ℹ️ **Shared dispatch entry**: this function resolves to the")
            lines.append(f"> same vaddr as `{effective}`. See that function's doc")
            lines.append("> for the detailed analysis.")
            lines.append("")

        # ── Entry points table ──
        eps = result.get("entry_candidates", [])
        if eps:
            lines.append("## Entry Points")
            lines.append("")
            lines.append("| VAddr | Offset | Type | Push Count |")
            lines.append("|-------|--------|------|------------|")
            for ep in eps:
                vad = ep.get("vaddr", 0)
                off = ep.get("offset", 0)
                etype = ep.get("type", "")
                pcount = ep.get("push_count", "")
                push_str = str(pcount) if pcount else "-"
                lines.append(f"| `0x{vad:x}` | `+{off}` | {etype} | {push_str} |")
            lines.append("")
            lines.append("*Entry point types:* `primary` = main entry (thunk), "
                         "`push_prologue` = multi-push sequence, "
                         "`frame_entry` = stack frame (`sub rsp`).*")
            lines.append("")

        # ── Disassembly (basic blocks) ──
        blocks: list = []
        if vaddr:
            try:
                blocks = self.binary.disassemble_basic_blocks(vaddr, max_size=2048)
            except Exception:
                blocks = []

        if blocks:
            lines.append("## Disassembly (Basic Blocks)")
            lines.append("")
            lines.append("```")
            for i, block in enumerate(blocks):
                start = block.get("start_vaddr", 0)
                end = block.get("end_vaddr", 0)
                bt = block.get("branch_target")
                ft = block.get("fallthrough")
                insns = block.get("instructions", [])
                lines.append(f"; Block {i}: 0x{start:x}–0x{end:x} "
                             f"({len(insns)} insns)")
                if bt:
                    lines.append(f";   Branch → 0x{bt:x}")
                if ft:
                    lines.append(f";   Fallthrough → 0x{ft:x}")
                for insn in insns:
                    adv = insn.get("vaddr", 0)
                    op = f"{insn['mnemonic']} {insn['op_str']}"
                    lines.append(f"  0x{adv:x}: {op}")
                lines.append("")
            lines.append("```")
            lines.append("")

        # ── Register flow: ARG_PTR reads ──
        arg_reads = result.get("arg_ptr_reads", [])
        if arg_reads:
            lines.append("## Register Flow: ARG_PTR Reads")
            lines.append("")
            lines.append("These instructions read from ARG_PTR (`0x500C6A0`), "
                         "indicating the function reads arguments from the "
                         "push+stack protocol:")
            lines.append("")
            for a in arg_reads:
                lines.append(f"- `0x{a['vaddr']:x}` (`+{a.get('offset', 0)}`): "
                             f"`{a.get('op', '')}`")
            lines.append("")

        # ── Register flow: SP_global accesses ──
        sp_access = result.get("sp_global_access", [])
        if sp_access:
            lines.append("## Register Flow: SP_global Accesses")
            lines.append("")
            lines.append("These instructions access SP_global (`0x500C638`), "
                         "indicating the SP-reset protocol:")
            lines.append("")
            for s in sp_access:
                write = "WRITE" if s.get("is_write") else "READ"
                lines.append(f"- {write}: `0x{s['vaddr']:x}` — `{s.get('op', '')}`")
            lines.append("")

        # ── Push function calls ──
        push_calls = result.get("push_calls", [])
        if push_calls:
            lines.append("## Push Function Calls")
            lines.append("")
            lines.append("| VAddr | Offset | Function | Type |")
            lines.append("|-------|--------|----------|------|")
            for pc in push_calls:
                vad = pc.get("vaddr", 0)
                off = pc.get("offset", 0)
                pfn = pc.get("push_function", "?")
                if "dbl" in pfn:
                    ptype = "double"
                elif "int" in pfn:
                    ptype = "int"
                elif "str" in pfn:
                    ptype = "string"
                else:
                    ptype = "?"
                lines.append(f"| `0x{vad:x}` | `+{off}` | `{pfn}` | {ptype} |")
            lines.append("")

        # ── Error code map ──
        ecs = result.get("error_codes", []) or result.get("error_codes_found", [])
        if ecs:
            lines.append("## Error Code Map")
            lines.append("")
            lines.append("| Address | Hex Code | Decimal RC | Context |")
            lines.append("|---------|----------|------------|---------|")
            for ec in ecs:
                vad = ec.get("vaddr", ec.get("address", 0))
                code = ec.get("error_code", ec.get("code", ec.get("checks", 0)))
                ctx = ec.get("guard_context", [])
                context_str = "; ".join(ctx[-2:]) if ctx else ""
                meaning = self._decode_error_code(code)
                try:
                    code_int = int(str(code), 0)
                except (ValueError, TypeError):
                    code_int = code
                if isinstance(code_int, int) and code_int > 0:
                    lines.append(f"| `0x{vad:x}` | `0x{code_int:x}` | {code_int} | "
                                 f"{context_str} — {meaning} |")
                else:
                    lines.append(f"| `0x{vad:x}` | `0x{code:x}` | {code} | "
                                 f"{context_str} — {meaning} |")
            lines.append("")
            lines.append("*Error codes: "
                         "459 = tsmat meta-field not found, "
                         "603 = type mismatch, "
                         "3300 = conformability error, "
                         "3498 = observation out of range, "
                         "3499 = variable not found.*")
            lines.append("")

        # ── Pool-header check locations ──
        pool_checks = result.get("pool_checks", [])
        if pool_checks:
            lines.append("## Pool-Header Check Locations")
            lines.append("")
            lines.append("These instructions check `tsmat[-0x94] == 0x2b` "
                         "(pool header sentinel):")
            lines.append("")
            for p in pool_checks:
                lines.append(f"- `0x{p['vaddr']:x}` (`+{p.get('offset', 0)}`): "
                             f"`{p.get('instruction', '')}`")
            lines.append("")

        # ── EDI checks (argument count branching) ──
        edi = result.get("edi_checks", [])
        if edi:
            lines.append("## Argument Count Branching")
            lines.append("")
            lines.append("These instructions check `edi` (argument count):")
            lines.append("")
            for e in edi:
                lines.append(f"- `0x{e['vaddr']:x}` — `{e.get('op', '')}`")
            lines.append("")

        # ── ASCII call-flow diagram ──
        if blocks:
            lines.append("## Call-Flow Diagram")
            lines.append("")
            lines.append("```")
            for i, block in enumerate(blocks):
                start = block.get("start_vaddr", 0)
                end = block.get("end_vaddr", 0)
                bt = block.get("branch_target")
                ft = block.get("fallthrough")
                label = f"B{i} [0x{start:x}..0x{end:x}]"

                is_entry = any(
                    ep.get("vaddr") == start for ep in eps
                )
                if is_entry:
                    label += " <<entry"
                    for ep in eps:
                        if ep.get("vaddr") == start:
                            if ep.get("type") == "primary":
                                label += ":primary"
                            elif "prologue" in (ep.get("type") or ""):
                                label += ":write"
                            elif ep.get("type") == "frame_entry":
                                label += ":frame"

                has_error = any(
                    ec.get("vaddr") in range(start, end + 1)
                    for ec in ecs
                )
                if has_error:
                    label += " [err]"

                lines.append(f"  {label}")
                if bt and ft:
                    lines.append(f"     ├─ cond → 0x{bt:x}")
                    lines.append(f"     └─ fall → 0x{ft:x}")
                elif bt:
                    lines.append(f"     └─ → 0x{bt:x}")
                lines.append("")
            lines.append("```")
            lines.append("")

        # ── Cross-references ──
        lines.append("## Cross-References")
        lines.append("")
        # Shared dispatch
        if di != "?":
            try:
                di_int = int(str(di))
                siblings = [
                    n for n, r in self._last_report.get("functions", {}).items()
                    if r.get("dispatch_index") == di_int and n != name
                ]
                if siblings:
                    lines.append(f"- **Shared dispatch index [{di}]**: ")
                    refs = ", ".join(f"[{s}]({s}.md)" for s in siblings)
                    lines.append(f"  {refs}")
            except ValueError:
                pass

        # Protocol pattern
        reg_entries = self.registry.lookup_by_type("protocol")
        matched = [
            r.name for r in reg_entries
            if r.data and r.data.get("protocol_type") == pt
        ]
        if matched:
            lines.append(f"- **Protocol pattern(s)**: ")
            refs = ", ".join(f"`{m}`" for m in matched)
            lines.append(f"  {refs}")

        # Push-function call graph
        push_targets = sorted(set(
            pc.get("push_function", "") for pc in push_calls
        ))
        if push_targets:
            lines.append(f"- **Calls push functions**: ")
            refs = ", ".join(f"[{t}]({t}.md)" for t in push_targets
                              if t.startswith("_push"))
            if not refs:
                refs = ", ".join(f"`{t}`" for t in push_targets)
            lines.append(f"  {refs}")

        # Registry patterns referencing this function
        all_entries = self.registry.list()
        refs = [
            e.name for e in all_entries
            if e.data and e.data.get("function") == name
        ]
        if refs:
            lines.append(f"- **Referenced by registry patterns**: ")
            refs_str = ", ".join(f"`{r}`" for r in refs)
            lines.append(f"  {refs_str}")

        lines.append("")
        lines.append("---")
        lines.append(f"*Generated by pystata-analyzer Framework — {datetime.utcnow().isoformat()}*")
        lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _decode_error_code(code: Any) -> str:
        """Return a human-readable meaning for a known error code."""
        known = {
            459: "tsmat meta-field not found",
            603: "type mismatch (expected double, got string or vice versa)",
            3300: "conformability error (observation or variable out of range)",
            3498: "observation index out of range",
            3499: "variable index out of range or not found",
            3200: "conformability error (general)",
            3201: "conformability error (size mismatch)",
            3301: "subscript out of range",
            3491: "system error (general)",
            3490: "system error (memory)",
            198: "expression evaluation error",
            111: "variable not found",
            108: "invalid syntax or name",
        }
        try:
            code_int = int(str(code), 0)
        except (ValueError, TypeError):
            return "unknown"
        return known.get(code_int, "unknown error code")

    # ═════════════════════════════════════════════════════════════════
    #  Architecture documentation (expanded)
    # ═════════════════════════════════════════════════════════════════

    def _generate_architecture_md(self) -> str:
        """Generate the living ARCHITECTURE.md from registry + analysis.

        Includes ASCII dispatch layout diagrams and multi-entry section.
        """
        lines = []
        lines.append("# Stata Binary Architecture (Living Document)")
        lines.append("")
        lines.append(f"*Generated from analysis of: `{self.binary.path}`*")
        lines.append(f"*SHA256: `{self.binary.sha256[:16]}`*")
        lines.append(f"*Functions analyzed: "
                     f"{len(self._last_report.get('functions', {}))}*")
        lines.append("")

        # ── Recent Changes ──
        changelog = self._compute_changelog()
        if changelog and changelog.get("total_changes", 0) > 0:
            lines.append("## Recent Changes")
            lines.append("")
            dt = datetime.fromtimestamp(changelog["timestamp"])
            lines.append(f"*{dt.isoformat()}*")
            if changelog.get("added_functions"):
                lines.append(f"- Added functions: {', '.join(f'`{n}`' for n in changelog['added_functions'][:5])}")
            if changelog.get("removed_functions"):
                lines.append(f"- Removed functions: {', '.join(f'`{n}`' for n in changelog['removed_functions'][:5])}")
            if changelog.get("changed_functions"):
                lines.append(f"- Changed functions: {len(changelog['changed_functions'])}")
            lines.append(f"- Total: {changelog['total_changes']} changes")
            lines.append("")

        # ── Address patterns ──
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

        # ── ASCII dispatch layout diagram ──
        functions = self._last_report.get("functions", {})
        lines.append("## Dispatch Architecture")
        lines.append("")
        lines.append("```")
        lines.append("Dispatch table layout:")
        lines.append("")
        lines.append("  Dispatch[0..1685]  ────→  Each entry is a 64-bit")
        lines.append("                           function pointer (vaddr)")
        lines.append("")
        lines.append("  st_* name table (118 entries):")
        lines.append("  ┌──────────────┬──────┬──────────────────────────┐")
        lines.append("  │ st_nobs(000) │ idx=0│→ _bist_nobs              │")
        lines.append("  │ st_nvar(066) │ idx=1│→ _bist_nvar              │")
        lines.append("  │ st_data(087) │ idx=25│→ _bist_data (read+write) │")
        lines.append("  │ st_global(135)│ ...  │→ _bist_global            │")
        lines.append("  │ ...          │      │                          │")
        lines.append("  └──────────────┴──────┴──────────────────────────┘")
        lines.append("")
        lines.append("  Dispatch → Implementation flow:")
        lines.append("    1. Caller pushes args (push+stack protocol)")
        lines.append("    2. Sets ARG_PTR = tsmat pointer chain")
        lines.append("    3. Calls dispatch table entry")
        lines.append("    4. Entry may be a thunk or direct impl")
        lines.append("    5. Thunk may implement SP-reset protocol")
        lines.append("       (writes descriptor addr → SP_global)")
        lines.append("    6. Function body reads ARG_PTR or SP_global")
        lines.append("    7. Pool-header check: tsmat[-0x94] == 0x2b")
        lines.append("    8. Returns result in tsmat[0]")
        lines.append("```")
        lines.append("")

        # ── Multi-entry dispatch diagram ──
        shared = self._find_shared_entries(functions)
        if shared:
            lines.append("### Multi-Entry Dispatch Functions")
            lines.append("")
            lines.append("Several dispatch indices share an implementation")
            lines.append("with multiple entry points:")
            lines.append("")
            for vaddr_hex, names in sorted(shared.items()):
                lines.append(f"**VAddr `0x{vaddr_hex}` → {', '.join(f'`{n}`' for n in names)}**")
                lines.append("")
                lines.append("```")
                lines.append(f"  0x{int(vaddr_hex, 16):x} ── primary entry")
                lines.append(f"     │")
                for n in names:
                    r = functions.get(n, {})
                    for ep in r.get("entry_candidates", []):
                        off = ep.get("offset", 0)
                        etype = ep.get("type", "")
                        pcount = ep.get("push_count", "")
                        label = f"  (write path)" if "prologue" in (etype or "") else ""
                        if pcount:
                            label += f" [{pcount} push]"
                        lines.append(f"     +{off} → {etype}{label}")
                lines.append("```")
                lines.append("")

        # ── Protocol patterns ──
        proto_patterns = self.registry.lookup_by_type("protocol")
        if proto_patterns:
            lines.append("## Protocol Patterns")
            lines.append("")
            for p in proto_patterns:
                lines.append(f"### {p.name}")
                lines.append("")
                lines.append(p.description)
                lines.append("")
                ptype = p.data.get("type", "")
                if ptype == "push_stack":
                    lines.append("```")
                    lines.append("Push+Stack Protocol:")
                    lines.append("  1. _pushdbl/_pushint/_pushstr alloc tsmat, update ARG_PTR")
                    lines.append("  2. Implementation indexes backward from ARG_PTR")
                    lines.append("  3. Reads tsmat[0] for double or GSO string pointer")
                    lines.append("  4. Pool-header check: tsmat[-0x94] == 0x2b")
                    lines.append("  5. Self-pointer fix: tsmat[-0x10] = tsmat")
                    lines.append("")
                    lines.append("  Stack layout after 2 pushes:")
                    lines.append("    ARG_PTR-16: tsmat[2] (second arg)")
                    lines.append("    ARG_PTR-8:  tsmat[1] (first arg)")
                    lines.append("    ARG_PTR:    next alloc slot")
                    lines.append("```")
                elif ptype == "sp_reset":
                    lines.append("```")
                    lines.append("SP-Reset Protocol:")
                    lines.append("  1. Thunk writes descriptor address to SP_global")
                    lines.append("  2. Implementation reads from global C struct")
                    lines.append("  3. No push function calls needed")
                    lines.append("  4. Always 0-arg or 1-arg scalar return")
                    lines.append("  5. Typical: _bist_nobs, _bist_nvar")
                    lines.append("```")
                elif ptype == "internal_global":
                    lines.append("```")
                    lines.append("Internal-Global Protocol:")
                    lines.append("  1. Caller goes through type-checking thunk first")
                    lines.append("  2. Implementation reads from Stata internal state")
                    lines.append("  3. Not usable from external code directly")
                    lines.append("  4. Typical: _bist_store write path")
                    lines.append("```")
                lines.append("")

        # ── Known function patterns (conventions) ──
        fn_patterns = self.registry.lookup_by_type("convention")
        if fn_patterns:
            lines.append("## Key Conventions")
            lines.append("")
            for p in fn_patterns:
                lines.append(f"### {p.name}")
                lines.append("")
                lines.append(p.description)
                lines.append("")

        # ── Protocol distribution ──
        lines.append("## Protocol Distribution")
        lines.append("")
        by_proto: dict[str, int] = {}
        for name, r in functions.items():
            pt = r.get("protocol_type", "unknown")
            by_proto[pt] = by_proto.get(pt, 0) + 1

        lines.append("| Protocol Type | Count | Examples |")
        lines.append("|---------------|-------|----------|")
        for pt, count in sorted(by_proto.items(), key=lambda x: -x[1]):
            examples = [n for n, r in functions.items()
                        if r.get("protocol_type") == pt][:3]
            ex_str = ", ".join(f"`{n}`" for n in examples) if examples else "-"
            lines.append(f"| {pt} | {count} | {ex_str} |")
        lines.append("")

        # ── Error code map ──
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

        # ── Cross-reference summary ──
        xref = self._build_cross_reference_index(functions)
        shared_entries = xref.get("shared_dispatch_entries", {})
        if shared_entries:
            lines.append("## Shared Dispatch Entry Groups")
            lines.append("")
            lines.append("| VAddr | Functions |")
            lines.append("|-------|-----------|")
            for vaddr_hex, names in sorted(shared_entries.items()):
                lines.append(f"| `{vaddr_hex}` | {', '.join(f'`{n}`' for n in names)} |")
            lines.append("")

        call_graph = xref.get("call_graph", {})
        if call_graph:
            lines.append("## Call Graph (Push Function Usage)")
            lines.append("")
            for fn, targets in sorted(call_graph.items()):
                lines.append(f"- `{fn}` → {', '.join(f'`{t}`' for t in targets)}")
            lines.append("")

        return "\n".join(lines)

    def _find_shared_entries(self, functions: dict[str, dict]
                             ) -> dict[str, list[str]]:
        """Find functions sharing the same vaddr (multi-entry dispatch)."""
        by_vaddr: dict[int, list[str]] = {}
        for name, result in functions.items():
            vaddr = result.get("vaddr")
            if vaddr:
                by_vaddr.setdefault(vaddr, []).append(name)
        return {
            hex(vaddr): names
            for vaddr, names in by_vaddr.items()
            if len(names) > 1
        }

    # ═════════════════════════════════════════════════════════════════
    #  Diff
    # ═════════════════════════════════════════════════════════════════

    def diff(self, other: "Framework") -> dict[str, Any]:
        """Compare this analysis with another binary version."""
        if not self._analyzed or not other._analyzed:
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


# Module-level constant for capstone availability check
try:
    from pystata_analyzer.helpers import HAS_CAPSTONE as _HAS_CS
    HAS_CAPSTONE_INSTALLED = _HAS_CS
except ImportError:
    HAS_CAPSTONE_INSTALLED = False
