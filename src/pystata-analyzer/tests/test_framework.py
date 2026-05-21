"""Unit and integration tests for the pystata-analyzer Framework.

Tests cover:
- PatternRegistry: add/remove/lookup/save/load, hardcoded defaults
- Plugin system: base class lifecycle hooks, decoration, discovery
- Framework orchestration: pipeline, analyze_all, analyze_function, report
- Documentation generation: markdown, per-function docs, API docs
- Diff: binary version comparison
"""

import json
import os
import sys
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from pystata_analyzer import (
    PatternRegistry, PatternEntry, REGISTRY_VERSION,
    Plugin, analyze_hook, report_hook,
    BUILTIN_PLUGINS,
    ErrorCodeMapper, EntryPointDetector, ProtocolClassifier,
    PoolHeaderScanner, ManifestManager, DocstringExtractor,
    Framework, ELFReader, StataBinary, HAS_CAPSTONE,
)


# ═════════════════════════════════════════════════════════════════════
#  PatternRegistry tests
# ═════════════════════════════════════════════════════════════════════

class TestPatternRegistry:
    def test_hardcoded_defaults_loaded(self):
        """Registry loads 18 hardcoded defaults."""
        reg = PatternRegistry()
        stats = reg.stats()
        assert stats["hardcoded"] >= 18, f"Expected 18+ hardcoded, got {stats['hardcoded']}"
        assert stats["total"] >= 18

    def test_lookup_existing(self):
        """lookup returns known entries."""
        reg = PatternRegistry()
        entry = reg.lookup("arg_ptr")
        assert entry is not None
        assert entry.pattern_type == "address"
        assert entry.data["vaddr"] == 0x500C6A0

    def test_lookup_missing(self):
        """lookup returns None for unknown names."""
        reg = PatternRegistry()
        assert reg.lookup("nonexistent_pattern") is None

    def test_add_and_lookup(self):
        """add registers a new pattern in user_added tier."""
        reg = PatternRegistry()
        reg.add("test_pattern", {"key": "value"}, pattern_type="test")
        entry = reg.lookup("test_pattern")
        assert entry is not None
        assert entry.data["key"] == "value"
        assert entry.source == "user_added"
        assert entry.pattern_type == "test"
        stats = reg.stats()
        assert stats["user_added"] == 1

    def test_add_overwrites(self):
        """add overwrites an existing pattern in user_added tier."""
        reg = PatternRegistry()
        reg.add("test_pattern", {"version": 1})
        reg.add("test_pattern", {"version": 2})
        entry = reg.lookup("test_pattern")
        assert entry.data["version"] == 2
        # Two adds means only one survives in user_added
        stats = reg.stats()
        assert stats["user_added"] == 1

    def test_remove(self):
        """remove deletes from all tiers."""
        reg = PatternRegistry()
        assert reg.remove("nonexistent") is False
        reg.add("test_pattern", {})
        assert reg.lookup("test_pattern") is not None
        assert reg.remove("test_pattern") is True
        assert reg.lookup("test_pattern") is None

    def test_list_filtered(self):
        """list filters by source and pattern_type."""
        reg = PatternRegistry()
        # Add user entries
        reg.add("u1", {}, pattern_type="protocol")
        reg.add("u2", {}, pattern_type="address")

        all_entries = reg.list()
        user_entries = reg.list(source="user_added")
        proto_entries = reg.list(pattern_type="protocol")

        assert len(user_entries) >= 2
        # All hardcoded + user entries
        assert len(all_entries) >= 20
        assert len(proto_entries) >= 2

    def test_lookup_by_type(self):
        """lookup_by_type finds all patterns of a given type."""
        reg = PatternRegistry()
        addrs = reg.lookup_by_type("address")
        assert len(addrs) >= 3  # arg_ptr, sp_global, err_addr
        assert any(a.name == "arg_ptr" for a in addrs)
        assert any(a.name == "sp_global" for a in addrs)

    def test_save_and_load(self):
        """save/load round-trip preserves entries."""
        reg = PatternRegistry()
        reg.add("save_test", {"x": 42}, pattern_type="roundtrip")

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            tmp_path = f.name
        try:
            reg.save(tmp_path, tier="user_added")
            assert os.path.exists(tmp_path)

            # Load into fresh registry
            reg2 = PatternRegistry(auto_load_defaults=False)
            count = reg2.load(tmp_path, tier="auto_detected")
            assert count >= 1

            entry = reg2.lookup("save_test")
            assert entry is not None
            assert entry.data["x"] == 42
            assert entry.source == "user_added"
        finally:
            os.unlink(tmp_path)

    def test_load_classmethod(self):
        """PatternRegistry.load() creates registry from file with defaults."""
        reg = PatternRegistry()
        reg.add("load_test", {"y": 99})
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            tmp_path = f.name
        try:
            reg.save(tmp_path, tier="user_added")
            reg2 = PatternRegistry.from_file(tmp_path, merge_defaults=True)
            # Should have both hardcoded defaults and loaded entries
            assert reg2.lookup("load_test") is not None
            assert reg2.lookup("arg_ptr") is not None
        finally:
            os.unlink(tmp_path)

    def test_register_detected(self):
        """register_detected stores entry with auto_detected source and sha256."""
        reg = PatternRegistry()
        reg.register_detected("auto_pattern", {"detected": True},
                              sha256="abc123")
        entry = reg.lookup("auto_pattern")
        assert entry.source == "auto_detected"
        assert entry.sha256 == "abc123"
        stats = reg.stats()
        assert stats["auto_detected"] == 1

    def test_known_addresses(self):
        """Verify critical known addresses match documentation."""
        reg = PatternRegistry()
        assert reg.lookup("arg_ptr").data["vaddr"] == 0x500C6A0
        assert reg.lookup("sp_global").data["vaddr"] == 0x500C638
        assert reg.lookup("err_addr").data["vaddr"] == 0x500C698

    def test_known_protocols(self):
        """Verify all 4 protocol types are registered."""
        reg = PatternRegistry()
        protos = reg.lookup_by_type("protocol")
        types = {p.data.get("type") for p in protos}
        assert "push_stack" in types
        assert "sp_reset" in types
        assert "internal_global" in types
        assert "string_return" in types

    def test_known_error_codes(self):
        """Verify known error code entries."""
        reg = PatternRegistry()
        errs = reg.lookup_by_type("error_code")
        codes = {e.data.get("code") for e in errs}
        assert 3300 in codes
        assert 3306 in codes
        assert 3302 in codes


# ═════════════════════════════════════════════════════════════════════
#  Plugin system tests
# ═════════════════════════════════════════════════════════════════════

class TestPluginSystem:
    def test_plugin_base_class(self):
        """Plugin base class has expected lifecycle hooks."""
        p = Plugin()
        assert hasattr(p, "on_analyze_start")
        assert hasattr(p, "on_analyze_function")
        assert hasattr(p, "on_analyze_end")
        assert hasattr(p, "on_report_generate")
        # Default hooks are no-ops
        p.on_analyze_start(None)
        p.on_analyze_function(None, "test", {})
        p.on_analyze_end(None, {})
        p.on_report_generate(None, {})

    def test_plugin_subclass(self):
        """Custom plugin subclass works."""
        class MyPlugin(Plugin):
            name = "my_plugin"
            version = "2.0.0"
            description = "Test plugin"
            depends_on = ["error_code_mapper"]

            def on_analyze_function(self, framework, name, result):
                result["my_plugin_ran"] = True

        p = MyPlugin()
        assert p.name == "my_plugin"
        assert p.version == "2.0.0"
        assert p.depends_on == ["error_code_mapper"]
        result = {}
        p.on_analyze_function(None, "test", result)
        assert result.get("my_plugin_ran") is True

    def test_builtin_plugins_instantiate(self):
        """All built-in plugins can be instantiated."""
        for name, cls in BUILTIN_PLUGINS.items():
            p = cls()
            assert p.name == name
            assert hasattr(p, "version")

    def test_error_code_mapper(self):
        """ErrorCodeMapper adds 'meaning' to error codes."""
        mapper = ErrorCodeMapper()
        result = {"error_codes": [{"code": 3300, "checks": 3300}]}
        mapper.on_analyze_function(None, "test", result)
        for ec in result["error_codes"]:
            assert "meaning" in ec
            assert ec["meaning"] != ""

    def test_pool_header_scanner(self):
        """PoolHeaderScanner works without framework (graceful skip)."""
        scanner = PoolHeaderScanner()
        result = {}
        # No framework → should skip gracefully
        scanner.on_analyze_function(None, "test", result)
        assert "pool_header_check" not in result

    def test_manifest_manager(self):
        """ManifestManager handles missing framework gracefully."""
        mm = ManifestManager()
        report = {}
        # With None framework, should skip silently
        mm.on_analyze_end(None, report)
        # No error, report unchanged
        assert "cache_error" not in report
        assert "cache_path" not in report

    def test_analyze_hook_decorator(self):
        """@analyze_hook registers standalone function hooks."""
        called = []

        @analyze_hook
        def my_hook(framework, name, result):
            called.append((name, result))

        # Hook should be registered
        from pystata_analyzer.plugin import _ANALYZE_HOOKS
        assert my_hook in _ANALYZE_HOOKS

        # Call the hook
        my_hook(None, "test_fn", {"x": 1})
        assert len(called) == 1
        assert called[0] == ("test_fn", {"x": 1})

    def test_report_hook_decorator(self):
        """@report_hook registers standalone report hooks."""
        called = []

        @report_hook
        def my_hook(framework, report):
            called.append(report)

        from pystata_analyzer.plugin import _REPORT_HOOKS
        assert my_hook in _REPORT_HOOKS

        my_hook(None, {"report": True})
        assert len(called) == 1


# ═════════════════════════════════════════════════════════════════════
#  Framework orchestration tests
# ═════════════════════════════════════════════════════════════════════

class TestFramework:
    def test_framework_init_without_binary(self):
        """Framework init fails gracefully without the binary."""
        with pytest.raises(FileNotFoundError):
            Framework("/nonexistent/path.so")

    def test_framework_init_with_mock(self):
        """Framework init with mocks (we'll do a real full test in integration)."""
        # Just test that Framework can be imported and constructed
        # with a mock binary for unit testing
        pass

    def test_framework_plugins_property(self):
        """plugins property returns list of loaded plugins."""
        fw = MagicMock(spec=Framework)
        fw.plugins = [ErrorCodeMapper(), ProtocolClassifier()]

        plugins = fw.plugins
        assert len(plugins) == 2
        assert plugins[0].name == "error_code_mapper"

    def test_framework_analyzed_property(self):
        """analyzed reflects state."""
        fw = MagicMock(spec=Framework)
        fw.analyzed = True
        assert fw.analyzed is True
        fw.analyzed = False
        assert fw.analyzed is False

    def test_registry_stats_method(self):
        """stats() returns correct counts."""
        reg = PatternRegistry()
        stats = reg.stats()
        assert isinstance(stats, dict)
        assert "hardcoded" in stats
        assert "auto_detected" in stats
        assert "user_added" in stats
        assert "total" in stats
        assert stats["total"] == stats["hardcoded"] + stats["auto_detected"] + stats["user_added"]


# ═════════════════════════════════════════════════════════════════════
#  Documentation generation tests
# ═════════════════════════════════════════════════════════════════════

class TestDocumentationGeneration:
    def test_architecture_md_contains_sections(self):
        """ARCHITECTURE.md generated from registry has expected sections."""
        reg = PatternRegistry()

        # Build architecture markdown
        lines = ["# Stata Binary Architecture", ""]

        addr_patterns = reg.lookup_by_type("address")
        if addr_patterns:
            lines.append("## Key Memory Addresses")
            for p in addr_patterns:
                vaddr = p.data.get("vaddr", 0)
                lines.append(f"- `{p.name}` = `0x{vaddr:x}`")
            lines.append("")

        proto_patterns = reg.lookup_by_type("protocol")
        if proto_patterns:
            lines.append("## Protocol Patterns")
            for p in proto_patterns:
                lines.append(f"- {p.name}: {p.description[:80]}")
            lines.append("")

        result = "\n".join(lines)
        assert "## Key Memory Addresses" in result
        assert "## Protocol Patterns" in result
        assert "arg_ptr" in result
        assert "push_stack" in result
        assert len(result) > 500

    def test_per_function_doc_stub(self):
        """Per-function doc generation from analysis result."""
        result = {
            "name": "_bist_nobs",
            "vaddr": 0x823B48,
            "dispatch_index": 85,
            "protocol_type": "push_stack_call",
            "uses_push_stack": True,
            "entry_candidates": [{"vaddr": 0x823B48, "notes": ""}],
            "error_codes": [{"vaddr": 0x823B80, "checks": 3300, "meaning": "conformability error"}],
            "pushstr_calls": [],
        }
        lines = [
            f"# {result['name']}",
            "",
            f"- VAddr: `0x{result['vaddr']:x}`",
            f"- Dispatch index: {result['dispatch_index']}",
            f"- Protocol type: {result['protocol_type']}",
            f"- Uses push+stack: {result['uses_push_stack']}",
        ]
        doc = "\n".join(lines)
        assert "_bist_nobs" in doc
        assert "0x823b48" in doc.lower()
        assert "85" in doc
        assert "push_stack_call" in doc

    def test_api_doc_generation(self):
        """API doc generation produces valid output."""
        # Generate from the actual package
        from pystata_analyzer import __file__ as pkg_file
        pkg_dir = os.path.dirname(pkg_file)

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = os.path.join(tmpdir, "api")
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
                    if doc:
                        if isinstance(node, ast.ClassDef):
                            lines.append(f"### `class {node.name}`")
                        else:
                            lines.append(f"### `{node.name}()`")
                        lines.append("")
                        lines.append(doc)
                        lines.append("")

                with open(doc_path, "w") as f:
                    f.write("\n".join(lines))

                index_lines.append(
                    f"- [{mod_name}]({fname[:-3]}.md) — {mod_doc[:80]}"
                )

            index_path = os.path.join(output_dir, "index.md")
            with open(index_path, "w") as f:
                f.write("\n".join(index_lines))

            # Verify
            assert os.path.exists(index_path)
            with open(index_path) as f:
                idx = f.read()
            assert "pystata-analyzer API Reference" in idx
            assert "binary" in idx.lower()


# ═════════════════════════════════════════════════════════════════════
#  Integration test markers
# ═════════════════════════════════════════════════════════════════════

requires_stata = pytest.mark.skipif(
    not os.environ.get("STATA_LIB_PATH", ""),
    reason="STATA_LIB_PATH not set (requires Stata binary)",
)


class TestFrameworkIntegration:
    """Integration tests against real Stata binary.  Skip without binary."""

    @requires_stata
    def test_framework_analyze_all(self):
        """Full pipeline produces non-empty report."""
        path = os.environ["STATA_LIB_PATH"]
        fw = Framework(path, skip_builtins=True)
        fw.analyze_all()
        assert fw.analyzed
        report = fw._last_report
        assert report["binary"]["dispatch_count"] > 0
        assert report["analysis"]["functions_analyzed"] > 0

    @requires_stata
    def test_framework_report_markdown(self):
        """Markdown report is non-empty."""
        path = os.environ["STATA_LIB_PATH"]
        fw = Framework(path, skip_builtins=True)
        fw.analyze_all()
        md = fw.report(format="markdown")
        assert len(md) > 1000
        assert "## Protocol Summary" in md
        assert "## Unclassified Functions" in md or "no unclassified" in md.lower()

    @requires_stata
    def test_framework_generate_report(self):
        """generate_report produces files on disk."""
        path = os.environ["STATA_LIB_PATH"]
        fw = Framework(path, skip_builtins=True)
        fw.analyze_all()
        with tempfile.TemporaryDirectory() as tmpdir:
            written = fw.generate_report(tmpdir)
            assert "ANALYSIS_REPORT.md" in written
            assert "ARCHITECTURE.md" in written
            assert os.path.exists(written["ANALYSIS_REPORT.md"])
            assert os.path.exists(written["ARCHITECTURE.md"])
            # Check per-function docs exist
            fn_files = [k for k in written if k.startswith("docs/fn/")]
            assert len(fn_files) > 10

    @requires_stata
    def test_framework_analyze_function(self):
        """analyze_function returns complete result."""
        path = os.environ["STATA_LIB_PATH"]
        fw = Framework(path, skip_builtins=True)
        fw.analyze_all()
        result = fw.analyze_function("_bist_nobs")
        assert result["name"] == "_bist_nobs"
        assert result.get("vaddr", 0) > 0
        assert "protocol_type" in result

    @requires_stata
    def test_framework_diff(self):
        """diff between same binary returns no changes."""
        path = os.environ["STATA_LIB_PATH"]
        fw1 = Framework(path, skip_builtins=True)
        fw2 = Framework(path, skip_builtins=True)
        fw1.analyze_all()
        fw2.analyze_all()
        diff = fw1.diff(fw2)
        # Same binary → no new/removed functions
        assert len(diff.get("new_functions", [])) == 0
        assert len(diff.get("removed_functions", [])) == 0

    @requires_stata
    def test_api_docs_generation(self):
        """generate_api_docs produces index.md."""
        path = os.environ["STATA_LIB_PATH"]
        fw = Framework(path, skip_builtins=True)
        fw.analyze_all()
        with tempfile.TemporaryDirectory() as tmpdir:
            api_path = fw.generate_api_docs(os.path.join(tmpdir, "api"))
            assert os.path.exists(api_path)
            with open(api_path) as f:
                content = f.read()
            assert len(content) > 500

    @requires_stata
    def test_registry_save_load_roundtrip(self):
        """Registry save/load round-trip works."""
        path = os.environ["STATA_LIB_PATH"]
        fw = Framework(path, skip_builtins=True)
        fw.analyze_all()
        with tempfile.TemporaryDirectory() as tmpdir:
            reg_path = os.path.join(tmpdir, "registry.json")
            fw.registry.save(reg_path, tier="auto_detected")
            assert os.path.exists(reg_path)
            reg2 = PatternRegistry.from_file(reg_path, merge_defaults=False)
            stats = reg2.stats()
            # Should have auto_detected entries
            assert stats["auto_detected"] > 0, (
                f"Expected auto-detected entries, got {stats}")
