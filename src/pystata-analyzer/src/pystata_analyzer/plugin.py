"""Plugin system for pystata-analyzer.

Provides:
- ``Plugin`` base class with lifecycle hooks
- ``@analyze_hook`` / ``@report_hook`` decorators for lightweight extensions
- Plugin discovery from a configurable directory
- Built-in plugins shipped with the package
"""

import importlib
import importlib.util
import inspect
import os
import sys
from typing import Any, Callable, Optional


# ═════════════════════════════════════════════════════════════════════
#  Hook registries (global, for standalone function hooks)
# ═════════════════════════════════════════════════════════════════════

_ANALYZE_HOOKS: list[Callable] = []
_REPORT_HOOKS: list[Callable] = []


def analyze_hook(fn: Callable) -> Callable:
    """Decorator: register *fn* as an analysis lifecycle hook.

    The function receives ``(framework, function_name, analysis_result)``
    and may modify *analysis_result* in place.
    """
    _ANALYZE_HOOKS.append(fn)
    return fn


def report_hook(fn: Callable) -> Callable:
    """Decorator: register *fn* as a report-generation hook.

    The function receives ``(framework, report_dict)`` and may modify
    *report_dict* in place.
    """
    _REPORT_HOOKS.append(fn)
    return fn


# ═════════════════════════════════════════════════════════════════════
#  Plugin base class
# ═════════════════════════════════════════════════════════════════════

class Plugin:
    """Base class for all analysis plugins.

    Subclass this and override any of the lifecycle hooks below.
    Plugins can declare dependencies on other plugins by name.

    Example::

        class MyPlugin(Plugin):
            name = "my_plugin"
            version = "1.0.0"
            depends_on = ["protocol_classifier"]

            def on_analyze_start(self, framework):
                print(f"Starting analysis of {framework.binary.path}")

            def on_analyze_function(self, framework, name, result):
                result["analyzed_by"] = self.name
    """

    name: str = "base_plugin"
    version: str = "0.1.0"
    description: str = ""
    depends_on: list[str] = []

    # ── Lifecycle hooks ─────────────────────────────────────────

    def on_analyze_start(self, framework: "Framework") -> None:
        """Called once when ``analyze_all()`` starts.

        Use for setup, clearing caches, opening files, etc.
        """

    def on_analyze_function(self, framework: "Framework",
                            name: str,
                            result: dict) -> None:
        """Called for each function during analysis.

        *result* is the analysis dict so far; plugins may mutate it.
        """

    def on_analyze_end(self, framework: "Framework",
                       report: dict) -> None:
        """Called after all functions are analyzed.

        *report* is the final report dict; plugins may add sections.
        """

    def on_report_generate(self, framework: "Framework",
                           report: dict) -> None:
        """Called when generating the formatted report.

        Plugins can add extra sections, diagrams, etc.
        """

    # ── Plugin discovery helpers ────────────────────────────────

    @classmethod
    def from_module(cls, mod_path: str) -> Optional["Plugin"]:
        """Load a Plugin subclass from a Python file path."""
        name = os.path.splitext(os.path.basename(mod_path))[0]
        spec = importlib.util.spec_from_file_location(name, mod_path)
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        for _, obj in inspect.getmembers(mod, inspect.isclass):
            if issubclass(obj, Plugin) and obj is not Plugin:
                return obj()
        return None

    def __repr__(self) -> str:
        return f"<Plugin {self.name} v{self.version}>"


# ═════════════════════════════════════════════════════════════════════
#  Built-in plugins
# ═════════════════════════════════════════════════════════════════════

class ErrorCodeMapper(Plugin):
    """Enrich analysis results with human-readable error-code meanings."""
    name = "error_code_mapper"
    version = "1.0.0"
    description = "Maps numeric error codes to human-readable meanings"

    ERROR_MAP = {
        0: "success",
        3300: "conformability error (wrong arg count/type)",
        3302: "type mismatch (expected different tsmat type)",
        3306: "index out of bounds (obs/var index out of range)",
        3498: "string buffer too small",
        3500: "invalid Stata name",
        3999: "observed value not found",
        410: "no data in memory",
        4598: "value label not found",
        3301: "matrix not found",
        3200: "conformability error (matrix)",
        111: "file not found",
        601: "file write error",
        198: "invalid syntax",
    }

    def on_analyze_function(self, framework, name, result):
        for ec in result.get("error_codes", []):
            code = ec.get("checks", ec.get("code", 0))
            ec["meaning"] = self.ERROR_MAP.get(code, f"unknown error code {code}")


class EntryPointDetector(Plugin):
    """Detect and classify multi-entry point patterns."""
    name = "entry_point_detector"
    version = "1.0.0"
    description = "Detects multi-entry dispatch functions (read/write split)"

    def on_analyze_function(self, framework, name, result):
        if framework is None or not framework.binary._analyzed:
            return
        try:
            entries = framework.binary.trace_entry_points(name)
            if entries:
                result["entry_points"] = entries
        except Exception:
            pass


class ProtocolClassifier(Plugin):
    """Classify functions into protocol categories."""
    name = "protocol_classifier"
    version = "1.0.0"
    description = "Classifies dispatch functions into known protocol types"

    def on_analyze_function(self, framework, name, result):
        if framework is None:
            return
        if not framework.binary._analyzed:
            return
        # Check if this is a string-return function (has pushstr calls
        # but no ARG_PTR reads)
        try:
            proto = framework.binary.analyze_protocol(name)
            result["protocol"] = proto
        except Exception:
            pass


class PoolHeaderScanner(Plugin):
    """Scan for pool-header check patterns in function implementations."""
    name = "pool_header_scanner"
    version = "1.0.0"
    description = "Detects tsmat pool-header sentinel checks"

    POOL_PATTERN = bytes([0x48, 0x8d, 0x48, 0x6c])  # lea rcx, [rax-0x94]

    def on_analyze_function(self, framework, name, result):
        if framework is None:
            return
        if not framework.binary._elf or not framework.binary._analyzed:
            return
        elf = framework.binary._elf
        vaddr = framework.binary.symbols.get(name)
        if vaddr is None:
            return
        off = vaddr - elf.text_vaddr
        if off < 0 or off + 512 > len(elf.text_raw):
            return
        chunk = elf.text_raw[off:off + 512]
        if self.POOL_PATTERN in chunk:
            result["pool_header_check"] = True


class ManifestManager(Plugin):
    """Manage manifest caching and staleness detection."""
    name = "manifest_manager"
    version = "1.0.0"
    description = "Handles cache save/load, manifest staleness checks"

    def on_analyze_end(self, framework, report):
        if framework is None:
            return
        if framework._auto_cache:
            try:
                path = framework.binary.save_cache()
                report["cache_path"] = path
            except Exception as e:
                report["cache_error"] = str(e)


class DocstringExtractor(Plugin):
    """Extract docstrings from source code for API documentation."""
    name = "docstring_extractor"
    version = "1.0.0"
    description = "Extracts docstrings from pystata-analyzer source modules"

    def on_report_generate(self, framework, report):
        docs = {}
        import pystata_analyzer
        pkg_dir = os.path.dirname(pystata_analyzer.__file__)
        for fname in sorted(os.listdir(pkg_dir)):
            if not fname.endswith(".py") or fname == "__pycache__":
                continue
            fpath = os.path.join(pkg_dir, fname)
            mod_docs = self._extract_module_docs(fpath)
            if mod_docs:
                docs[fname] = mod_docs
        report["api_docs"] = docs

    def _extract_module_docs(self, path: str) -> list[dict]:
        """Extract class and function docstrings from a Python file."""
        results = []
        try:
            with open(path) as f:
                content = f.read()
            import ast
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if not isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                doc = ast.get_docstring(node)
                if doc:
                    kind = "class" if isinstance(node, ast.ClassDef) else "function"
                    results.append({
                        "name": node.name,
                        "kind": kind,
                        "docstring": doc.strip()[:500],
                        "lineno": node.lineno,
                    })
        except (SyntaxError, OSError):
            pass
        return results


class LiveProtocolValidator(Plugin):
    """Validate dispatch function protocols against a live Stata engine.

    Automatically connects to a running Stata engine (via pystata_x) and
    tests each dispatch function to verify its calling convention, check
    error codes, dump tsmat memory, and report actual return values.

    Falls back silently if no Stata engine is available (no crash).
    """
    name = "live_protocol_validator"
    version = "1.0.0"
    description = "Tests dispatch function protocols against live Stata engine"
    depends_on: list[str] = []

    def __init__(self):
        super().__init__()
        self._validator: Any = None

    def on_analyze_start(self, framework):
        """Try to initialize the engine connection."""
        try:
            from pystata_analyzer.live_protocol import LiveProtocolValidatorPlugin
            self._validator = LiveProtocolValidatorPlugin()
            status = self._validator.initialize()
            if status.get("status") in ("ok", "partial"):
                print(f"[live] Stata engine connected ({status.get('syms_count', 0)} symbols)")
            else:
                print(f"[live] Engine init: {status.get('status')} — running in static mode")
                self._validator = None
        except Exception as e:
            print(f"[live] Cannot connect to Stata engine: {e}")
            self._validator = None

    def on_analyze_function(self, framework, name, result):
        """Validate each function that has protocol issues."""
        if self._validator is None:
            return
        if not result.get("unclassified") and result.get("protocol_validation", {}).get("valid") != False:
            return

        try:
            # Guess args from static analysis
            args = self._guess_args(result)
            rtype = self._guess_return_type(result)

            diag = self._validator.engine.diagnose_dispatch(
                name, *args, return_type=rtype)

            if diag.get("call_completed") and not diag.get("error_set"):
                inferred = diag.get("inferred_protocol", {})
                if inferred:
                    result["live_protocol"] = inferred
                    # Also set the protocol_type based on live results
                    if inferred.get("return_type") and result.get("protocol_type") == "unknown":
                        result["protocol_type"] = inferred["protocol"]

            # Always record the diagnostics
            result["live_diagnostics"] = {
                "vaddr": diag.get("vaddr"),
                "call_completed": diag.get("call_completed"),
                "error_code": diag.get("error_code"),
                "error_set": diag.get("error_set"),
                "return_value": diag.get("return_value"),
                "pool_ok": diag.get("tsmat_after_push", {}).get("pool_header", {}).get("tsmat_pool_ok"),
                "self_ptr_ok": diag.get("tsmat_after_push", {}).get("self_ptr", {}).get("ok"),
            }
        except Exception as e:
            result["live_diagnostics"] = {"error": str(e)}

    def on_analyze_end(self, framework, report):
        """Generate a summary of live validation results."""
        if self._validator is None:
            return
        live_summary = {"validated": 0, "failed": 0, "bypassed": 0}
        for name, result in report.get("functions", {}).items():
            ld = result.get("live_diagnostics", {})
            if ld:
                live_summary["validated"] += 1
                if ld.get("error_set"):
                    live_summary["failed"] += 1
            else:
                live_summary["bypassed"] += 1
        report["live_validation_summary"] = live_summary

    def _guess_args(self, result: dict) -> list:
        """Guess arguments from function analysis."""
        pt = result.get("protocol_type", "")
        di = result.get("dispatch_index")
        if di == 87:  # _bist_data/_bist_store combined
            return [1, 1]  # var[1], obs[1] in 0-based
        if pt == "no_stack_args" or di in (0, 1, 2):
            return []
        if pt == "string_return" or "string" in pt:
            return [b"test", 1]
        return [b"test", 1]

    def _guess_return_type(self, result: dict) -> str:
        """Guess return type from function analysis."""
        pt = result.get("protocol_type", "")
        if pt == "string_return" or pt == "read_write" and result.get("push_calls", []):
            return "string"
        push_types = {p.get("push_function") for p in result.get("push_calls", [])}
        if "_pushstr" in push_types:
            return "string"
        return "double"


# ═════════════════════════════════════════════════════════════════════
#  Plugin loader
# ═════════════════════════════════════════════════════════════════════

BUILTIN_PLUGINS: dict[str, type[Plugin]] = {
    "error_code_mapper": ErrorCodeMapper,
    "entry_point_detector": EntryPointDetector,
    "protocol_classifier": ProtocolClassifier,
    "pool_header_scanner": PoolHeaderScanner,
    "manifest_manager": ManifestManager,
    "docstring_extractor": DocstringExtractor,
    "live_protocol_validator": LiveProtocolValidator,
}


def discover_plugins(plugin_dir: Optional[str] = None) -> list[Plugin]:
    """Discover plugins from *plugin_dir* (loads .py files)."""
    plugins: list[Plugin] = []
    if plugin_dir and os.path.isdir(plugin_dir):
        for fname in sorted(os.listdir(plugin_dir)):
            if not fname.endswith(".py") or fname.startswith("_"):
                continue
            fpath = os.path.join(plugin_dir, fname)
            plugin = Plugin.from_module(fpath)
            if plugin:
                plugins.append(plugin)
    return plugins


def resolve_dependencies(plugins: list[Plugin]) -> list[Plugin]:
    """Order plugins so dependencies are before dependents.

    Raises ``ValueError`` if a dependency is missing or circular.
    """
    name_map = {p.name: p for p in plugins}
    ordered: list[Plugin] = []
    visited: set[str] = set()

    def _visit(name: str, path: list[str]) -> None:
        if name in visited:
            return
        if name in path:
            raise ValueError(f"Circular dependency: {' → '.join(path + [name])}")
        plugin = name_map.get(name)
        if plugin is None:
            raise ValueError(f"Missing dependency: {name}")
        path.append(name)
        for dep in plugin.depends_on:
            _visit(dep, path)
        path.pop()
        visited.add(name)
        ordered.append(plugin)

    for plugin in plugins:
        _visit(plugin.name, [])
    return ordered
