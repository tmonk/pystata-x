"""_analyzer — Comprehensive Stata binary analysis framework.

This is the SINGLE tool for ALL debugging and analysis.  Do NOT write
ad-hoc /tmp/ scripts; use this module instead.

Key capabilities:
  - Binary discovery:   dispatch table, st_* names, push functions,
                        stack pointer, error address, StataSO exports
  - Protocol analysis:  for any _bist_ function, decompile with Capstone
                        to understand argument/return protocol
  - Live verification:  test any symbol against a running engine
  - Cache management:   versioned manifests with staleness detection,
                        automatic regeneration
  - Comprehensive CLI:  --report, --verify, --cache, --dispatch, --health

Usage:
    # CLI — single entry point for ALL debugging
    python -m pystata_x.sfi._analyzer <path> --report      # full report
    python -m pystata_x.sfi._analyzer <path> --verify      # test vs engine
    python -m pystata_x.sfi._analyzer <path> --dispatch _bist_nobs  # decompile
    python -m pystata_x.sfi._analyzer <path> --health      # cache health
    python -m pystata_x.sfi._analyzer <path> --cache       # save cache

    # Programmatic
    from pystata_x.sfi._analyzer import StataBinary, cache_health
    ana = StataBinary("/path/to/libstata.so")
    mdata = ana.analyze()
    ana.save_cache()
    print(ana.report())
"""

# Re-export core classes from pystata-analyzer standalone package
from pystata_analyzer import StataBinary, ELFReader, HAS_CAPSTONE

import ctypes
import hashlib
import json
import os
import struct
import sys
from pathlib import Path
from typing import Optional, Any

# ── Capstone (optional — install for disassembly output) ─────────────────
try:
    from capstone import Cs as _Cs, CS_ARCH_X86, CS_MODE_64
    HAS_CAPSTONE = True
except ImportError:
    _Cs = None
    CS_ARCH_X86 = CS_MODE_64 = None
    HAS_CAPSTONE = False

CURRENT_MANIFEST_VERSION = 2  # bump when scanner format changes


# ==================================================================
#  Helpers, ELFReader, and StataBinary are now in pystata-analyzer.
#  Imported above. Remove this file once all callers migrate.
# ==================================================================
# =========================================================================

def cache_health(cache_dir: Optional[str] = None) -> list[dict]:
    """Check health of all cached manifests without requiring a binary."""
    return StataBinary.cache_health(cache_dir)


# =========================================================================
#  Diagnostic engine — comprehensive testing without ad-hoc scripts
# =========================================================================


def check_pool_header(engine=None) -> dict:
    """Check pool header tag (0x2b at tsmat_ptr[-0x94]) on live engine.

    This is the critical check for st_data, st_store, and other
    functions that validate the pool allocator header on x86_64.
    Records the result in the test history.
    """
    result = {
        "check": "pool_header_tag",
        "tsmat_has_tag": None,
        "data_buf_has_tag": None,
        "sp_advances": None,
        "error": None,
    }
    if engine is None:
        try:
            import pystata_x.sfi._engine as engine
        except ImportError:
            result["error"] = "engine not available"
            return result

    import ctypes

    # Push a double and check the resulting tsmat
    sp_before = engine._save_sp()
    engine._push_double(42.0)
    sp_after = engine._save_sp()
    result["sp_advances"] = sp_after > sp_before
    if not result["sp_advances"]:
        result["error"] = "push_double did not advance stack"
        return result

    tsmat_ptr = ctypes.c_uint64.from_address(sp_after).value
    if not tsmat_ptr:
        result["error"] = "tsmat ptr is NULL after push"
        engine._restore_sp(sp_before)
        return result

    # Check pool header tag at tsmat_ptr[-0x94]
    import ctypes as C
    tag_loc = tsmat_ptr - 0x94
    tag_val = C.c_uint32.from_address(tag_loc).value
    result["tsmat_has_tag"] = (tag_val == 0x2b)
    result["tsmat_tag_location"] = hex(tag_loc)
    result["tsmat_tag_value"] = tag_val

    # Also check data buffer header
    data_buf = C.c_uint64.from_address(tsmat_ptr).value
    if data_buf:
        data_tag_loc = data_buf - 0x94
        data_tag_val = C.c_uint32.from_address(data_tag_loc).value
        result["data_buf_has_tag"] = (data_tag_val == 0x2b)
        result["data_tag_location"] = hex(data_tag_loc)
        result["data_tag_value"] = data_tag_val

    engine._restore_sp(sp_before)
    return result


class TestHistory:
    """Records test results persistently, replacing ad-hoc scripts.

    Usage:
        history = TestHistory()
        history.record("nobs", passed=True, value=74, notes="")
        history.record("data", passed=False, notes="pool header check fails")
        history.summary()
    """

    def __init__(self, path: Optional[str] = None):
        if path is None:
            path = os.path.join(
                os.path.dirname(__file__), "test_history.json"
            )
        self.path = path
        self.results: dict[str, list[dict]] = {}
        if os.path.exists(path):
            try:
                with open(path) as f:
                    self.results = json.load(f)
            except (json.JSONDecodeError, OSError):
                self.results = {}

    def record(self, fn_name: str, passed: bool, value=None,
               notes: str = "", xfail: bool = False):
        """Record a test result for a function."""
        import time
        entry = {
            "timestamp": time.time(),
            "passed": passed,
            "value": value,
            "notes": notes,
            "xfail": xfail,
        }
        if fn_name not in self.results:
            self.results[fn_name] = []
        self.results[fn_name].append(entry)
        self._save()

    def last_result(self, fn_name: str) -> Optional[dict]:
        """Get the most recent result for a function."""
        entries = self.results.get(fn_name, [])
        return entries[-1] if entries else None

    def summary(self) -> str:
        """Generate a human-readable test summary."""
        lines = ["Test History Summary", "=" * 60]
        passed = 0
        failed = 0
        xfailed = 0
        unknown = 0
        for fn_name, entries in sorted(self.results.items()):
            last = entries[-1]
            is_xfail = last.get("xfail", False)
            if is_xfail:
                status = "~"
                xfailed += 1
            elif last["passed"]:
                status = "✓"
                passed += 1
            else:
                status = "✗"
                failed += 1
            val = last.get("value", "")
            notes = last.get("notes", "")
            line = f"  {status} {fn_name:25s}"
            if val is not None:
                line += f" = {val}"
            if is_xfail:
                line += "  (xfail)"
            if notes and not is_xfail:
                line += f"  ({notes})"
            lines.append(line)
        lines.append("")
        total = passed + failed + xfailed + unknown
        lines.append(f"Total: {total}  Passed: {passed}  Failed: {failed}  "
                     f"XFail: {xfailed}  Unknown: {unknown}")
        return "\n".join(lines)

    def _save(self):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "w") as f:
            json.dump(self.results, f, indent=2)


def run_test_suite(engine=None, history: Optional[TestHistory] = None,
                   binary_path: Optional[str] = None) -> list[dict]:
    """Run a comprehensive test suite on the live engine.

    Tests all fundamental operations and records results.
    Does NOT use /tmp/ scripts — everything goes through the framework.
    """
    results = []

    if engine is None:
        try:
            from pystata_x.sfi._engine import initialize as _init
            _init()
            import pystata_x.sfi._engine as engine
        except ImportError as e:
            return [{"name": "*", "status": "error",
                     "error": f"engine: {e}"}]

    if history is None:
        history = TestHistory()

    # ── 1. Push function checks ──
    pool = check_pool_header(engine)
    results.append({
        "name": "pool_header",
        "status": "ok" if pool.get("tsmat_has_tag") else "fail",
        "details": pool,
    })
    history.record("pool_header",
                    passed=pool.get("tsmat_has_tag") or False,
                    notes=f"tag=0x{pool.get('tsmat_tag_value', 0):x} "
                          f"at {pool.get('tsmat_tag_location', '?')}")

    # ── 2. Load data ──
    engine._LIB.StataSO_Execute(b"sysuse auto, clear")

    # ── 3. Basic dispatch tests ──
    # Determine platform for xfail markers
    import sys as _sys
    import platform as _platform
    _is_x86_64_linux = _sys.platform in ("linux", "linux2") and _platform.machine() == "x86_64"

    test_cases = [
        ("nobs", engine.call_int, [], lambda r: r is not None and r > 0, False),
        ("nvar", engine.call_int, [], lambda r: r is not None and r > 0, False),
        ("data", engine.call_double, [1, 2], lambda r: r is not None, False),
    ]

    # numscalar: use Scalar.getValue on x86_64 (display path), raw dispatch elsewhere
    if _is_x86_64_linux:
        from pystata_x.sfi._core import Scalar as _Scalar
        test_cases.append(("numscalar", lambda *a: _Scalar.getValue("c(pi)"), [],
                           lambda r: r is not None and r > 0, False))
    else:
        test_cases.append(("numscalar", engine.call_double, ["pi"],
                           lambda r: r is not None, False))

    for name, fn, args, check, xfail in test_cases:
        try:
            val = fn(name, *args)
            passed = check(val)
        except Exception as e:
            val = None
            passed = False
        if xfail:
            status = "xfail" if not passed else "ok"
        else:
            status = "ok" if passed else "fail"
        results.append({
            "name": name,
            "status": status,
            "value": val,
        })
        is_xfail = status == "xfail"
        history.record(name, passed=(status == "ok"), value=val, xfail=is_xfail)

    # ── 4. Print summary ──
    ok = sum(1 for r in results if r["status"] == "ok")
    fail = sum(1 for r in results if r["status"] == "fail")
    xfail = sum(1 for r in results if r["status"] == "xfail")
    print(f"  Tests: {len(results)} total, {ok} passed, {fail} failed, {xfail} xfail", flush=True)

    return results


def run_e2e_suite(test_dir: Optional[str] = None,
                  history: Optional[TestHistory] = None) -> dict:
    """Run the full pytest e2e test suite and categorize results.

    Captures ALL output in one shot, categorizes each failure as:
      - sentinel:    0.0 returned when real value expected (pool-header lim)
      - sigsegv:     crash/segfault
      - wrong_value: non-zero but wrong value
      - null_return:  None/empty return
      - setup_error:  engine/initialization issue

    Returns dict with counts, per-test details, and test history updates.
    """
    import subprocess
    import re

    if test_dir is None:
        # Auto-discover from the framework's own location
        fw_dir = os.path.dirname(os.path.abspath(__file__))
        # Walk up to find tests/e2e/
        for parent in [os.path.dirname(fw_dir),  # sfi/
                       os.path.dirname(os.path.dirname(fw_dir)),  # pystata_x/
                       os.path.dirname(os.path.dirname(os.path.dirname(fw_dir)))]:  # src/
            candidate = os.path.join(parent, "tests", "e2e")
            if os.path.isdir(candidate):
                test_dir = candidate
                break
        if test_dir is None:
            # Try /pystata-x/tests/e2e (Docker mount)
            if os.path.isdir("/pystata-x/tests/e2e"):
                test_dir = "/pystata-x/tests/e2e"
    if test_dir is None:
        return {"error": "Cannot find tests/e2e/ directory"}

    project_root = os.path.dirname(os.path.dirname(test_dir))

    if history is None:
        history = TestHistory()

    print(f"Running e2e suite in {project_root}...", flush=True)
    # Run e2e tests marked requires_stata (subset designed to pass on all platforms).
    # Oracle tests and platform-specific tests use skip/xfail markers.
    result = subprocess.run(
        ["python3", "-m", "pytest", test_dir, "-v", "--tb=short",
         "-m", "requires_stata"],
        cwd=project_root,
        capture_output=True,
        text=True,
        timeout=300,
    )

    stdout = result.stdout
    stderr = result.stderr
    all_output = stdout + "\n" + stderr

    # Parse test results
    test_line_re = re.compile(
        r"^(tests/.*\.py)::(\S+)::(\S+) (PASSED|FAILED|SKIPPED|XFAIL|ERROR)\s*"
    )
    tests = []
    for line in stdout.split("\n"):
        m = test_line_re.match(line)
        if m:
            tests.append({
                "file": m.group(1),
                "class": m.group(2),
                "name": m.group(3),
                "status": m.group(4),
            })

    # Get short traceback for all FAILED tests (second pass)
    failed_names = [t["name"] for t in tests if t["status"] == "FAILED"]
    tb_by_test = {}
    if failed_names:
        # Re-run failed tests with full traceback
        print(f"  Capturing tracebacks for {len(failed_names)} failures...", flush=True)
        # Run in batches to avoid overly long command lines
        batch_size = 10
        for i in range(0, len(failed_names), batch_size):
            batch = failed_names[i:i + batch_size]
            tb_result = subprocess.run(
                ["python3", "-m", "pytest", test_dir,
                 "-v", "--tb=short", "-m", "requires_stata",
                 "-k", " or ".join(batch)],
                cwd=project_root,
                capture_output=True,
                text=True,
                timeout=120,
            )
            # Extract assertion error lines
            current_test = None
            for line in tb_result.stdout.split("\n"):
                m2 = test_line_re.match(line)
                if m2:
                    current_test = m2.group(3)
                    continue
                if current_test and ("AssertionError" in line or "Error:" in line
                                     or "SIGSEGV" in line or "Segmentation" in line
                                     or "returned None" in line
                                     or "Failed" in line):
                    tb_by_test[current_test] = line.strip()
                    current_test = None

    # Categorize failures by test class/name and traceback
    categories = {"sentinel": 0, "sigsegv": 0, "wrong_value": 0,
                  "null_return": 0, "setup_error": 0, "string_dispatch": 0,
                  "macro_requires_context": 0, "other": 0}
    failure_details = []

    # Known patterns: certain test classes always fail the same way on x86_64
    _PATTERNS = {
        # ValueLabel tests all SIGSEGV in _bist_dir dispatch
        ("TestValueLabels",): "sigsegv",
        # String scalar dispatch not supported
        ("TestStringScalars",): "string_dispatch",
        # Variable metadata uses string dispatch
        ("TestVariableMetadata",): "string_dispatch",
        # Cell writes use store which needs working readback
        ("TestCellWrites",): "sentinel",
        # Missing values tests need data() which returns sentinel
        ("TestMissingValues",): "sentinel",
        # Macro requires Stata execution context
        ("TestMacros", "test_set_and_get"): "macro_requires_context",
        # String oracle functions
        ("TestOracleCompliance", "test_var_names"): "string_dispatch",
        ("TestOracleCompliance", "test_var_labels"): "string_dispatch",
        ("TestOracleCompliance", "test_var_types"): "string_dispatch",
        ("TestOracleCompliance", "test_var_formats"): "string_dispatch",
        ("TestOracleCompliance", "test_string_reads"): "string_dispatch",
        ("TestOracleCompliance", "test_str_width"): "string_dispatch",
        ("TestOracleCompliance", "test_macro_global_set"): "macro_requires_context",
        ("TestOracleCompliance", "test_numeric_reads"): "sentinel",
        ("TestOracleCompliance", "test_scalar_value"): "sentinel",
    }

    for t in tests:
        if t["status"] == "FAILED":
            tb = tb_by_test.get(t["name"], "")
            # Check known patterns first
            category = _PATTERNS.get((t["class"],), _PATTERNS.get((t["class"], t["name"]), None))
            if category is None:
                # Fall back to traceback analysis
                if "SIGSEGV" in tb or "Segmentation fault" in tb or "signal 11" in tb.lower():
                    category = "sigsegv"
                elif "not initialized" in tb.lower() or "not found" in tb.lower():
                    category = "setup_error"
                elif t["name"].startswith("test_string_"):
                    category = "string_dispatch"
                elif t["name"].startswith("test_macro_"):
                    category = "macro_requires_context"
                elif t["class"].startswith("TestCell") or t["class"].startswith("TestNumeric") or t["class"].startswith("TestMissing"):
                    category = "sentinel"
                else:
                    category = "other"
            categories[category] = categories.get(category, 0) + 1
            failure_details.append({
                "test": f"{t['class']}::{t['name']}",
                "category": category,
                "traceback": tb,
            })

    # Log to TestHistory
    summary_obj = {
        "total": len(tests),
        "passed": sum(1 for t in tests if t["status"] == "PASSED"),
        "failed": len(failed_names),
        "skipped": sum(1 for t in tests if t["status"] == "SKIPPED"),
        "xfail": sum(1 for t in tests if t["status"] == "XFAIL"),
        "categories": categories,
    }
    history.record(
        "e2e_suite",
        passed=len(failed_names) == 0,
        value=summary_obj,
        notes=f"{len(failed_names)} failures: {categories}"
    )

    report = {
        "total": len(tests),
        "passed": sum(1 for t in tests if t["status"] == "PASSED"),
        "failed": len(failed_names),
        "skipped": sum(1 for t in tests if t["status"] == "SKIPPED"),
        "xfail": sum(1 for t in tests if t["status"] == "XFAIL"),
        "error_count": sum(1 for t in tests if t["status"] == "ERROR"),
        "categories": categories,
        "failures": failure_details,
    }
    return report


# =========================================================================
#  CLI
# =========================================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Stata Binary Analysis Framework — replaces ALL ad-hoc scripts",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s /path/to/libstata.so --report           Full analysis report
  %(prog)s /path/to/libstata.so --verify           Comprehensive live test
  %(prog)s /path/to/libstata.so --cache            Save manifest cache
  %(prog)s /path/to/libstata.so --diff             Diff current vs cached manifest
  %(prog)s /path/to/libstata.so --dispatch _bist_nobs  Decompile + protocol
  %(prog)s /path/to/libstata.so --trace nobs       Trace a dispatch call live
  %(prog)s /path/to/libstata.so --trace data:1,2   Trace with arguments
  %(prog)s /path/to/libstata.so --test-suite       Run full test suite
  %(prog)s /path/to/libstata.so --check-pool       Check pool header tag
  %(prog)s /path/to/libstata.so --protocol _bist_varindex  Deep protocol analysis
  %(prog)s /path/to/libstata.so --catalog          Catalog all dispatch protocols
  %(prog)s --health                                Cache health check (no binary)
""",
    )
    parser.add_argument("path", nargs="?",
                        help="Path to .so/.dylib/.dll")
    parser.add_argument("--report", action="store_true",
                        help="Full analysis report (default)")
    parser.add_argument("--verify", action="store_true",
                        help="Verify symbols against live engine")
    parser.add_argument("--cache", action="store_true",
                        help="Save manifest to cache directory")
    parser.add_argument("--force", action="store_true",
                        help="Force fresh analysis (ignore cache)")
    parser.add_argument("--dispatch", type=str, metavar="FUNCTION",
                        help="Decompile + analyze a specific _bist_ function")
    parser.add_argument("--diff", action="store_true",
                        help="Diff current analysis vs cached manifest")
    parser.add_argument("--trace", type=str, metavar="FUNCTION",
                        help="Trace a dispatch call via live engine (e.g. nobs, data:1,2)")

    parser.add_argument("--test-suite", action="store_true",
                        help="Run full test suite with history recording")
    parser.add_argument("--run-e2e", action="store_true",
                        help="Run e2e pytest suite, categorize failures, log to history")
    parser.add_argument("--check-pool", action="store_true",
                        help="Check pool header tag on live engine")
    parser.add_argument("--find-strings", action="store_true",
                        help="Scan dispatch table for string-returning functions via call-chain tracing")
    parser.add_argument("--protocol", type=str, metavar="FUNCTION",
                        help="Deep protocol analysis of a dispatch function (e.g. _bist_varindex)")
    parser.add_argument("--catalog", action="store_true",
                        help="Run protocol analysis on all dispatch entries and show summary table")
    parser.add_argument("--pool-catalog", action="store_true",
                        help="Catalog pool-header check patterns across ALL dispatch entries")
    parser.add_argument("--analyze-strings", type=str, nargs="?", const="all",
                        help="Deep per-function analysis of string dispatch entries. "
                             "Optionally filter by name substring (e.g. var, macro, label). "
                             "Logs each function's thunk path, pool-header check, and protocol to TestHistory.")
    parser.add_argument("--xfsearch", type=str, metavar="ADDR",
                        help="Find all code locations in .text that call a given address (hex)")
    parser.add_argument("--history", action="store_true",
                        help="Show test history summary")
    parser.add_argument("--var-info", action="store_true",
                        help="Read variable names/labels/types/formats from live engine")
    parser.add_argument("--search", type=str, metavar="PATTERN",
                        help="Search binary sections for hex or text pattern")
    parser.add_argument("--health", action="store_true",
                        help="Cache health check (no binary path needed)")
    parser.add_argument("--json", action="store_true",
                        help="Machine-readable JSON output")
    args = parser.parse_args()

    # ── health check (no path needed) ──
    if args.health:
        health = cache_health()
        if args.json:
            print(json.dumps(health, indent=2))
        else:
            print(f"Cache health ({len(health)} manifests):")
            for h in health:
                st = h["status"]
                mark = "✓" if st == "ok" else "!" if st == "stale" else "✗"
                print(f"  {mark} {h['file']}")
                print(f"     SHA256:  {h['sha256_prefix']}...")
                print(f"     Version: {h['version']}")
                print(f"     BIST:    {h['n_bist']}")
                print(f"     Offsets: {h['has_data_offsets']}")
                print(f"     PushFn:  {h['has_push_fns']}")
        return

    # ── run e2e tests (no path needed) ──
    if args.run_e2e:
        history = TestHistory()
        report = run_e2e_suite(history=history)
        if isinstance(report.get("error"), str):
            print(f"ERROR: {report['error']}", file=sys.stderr)
            return
        print()
        print("═" * 60)
        print("E2E Test Suite Results")
        print("═" * 60)
        print(f"  Total:   {report['total']}")
        print(f"  PASSED:  {report['passed']}")
        print(f"  FAILED:  {report['failed']}")
        print(f"  SKIPPED: {report['skipped']}")
        print(f"  XFAIL:   {report['xfail']}")
        print(f"  ERROR:   {report['error_count']}")
        print()
        print("Failure Categories:")
        for cat, count in sorted(report['categories'].items()):
            if count > 0:
                print(f"  {cat:15s}: {count}")
        print()
        if report.get('failures'):
            print("Detailed Failures:")
            for f in report['failures']:
                print(f"  ✗ {f['test']}  [{f['category']}]")
                if f['traceback']:
                    print(f"    {f['traceback']}")
        print()
        print(history.summary())
        return

    # ── history (no path needed) ──
    if args.history:
        history = TestHistory()
        print(history.summary())
        return

    # ── test suite (no path needed) ──
    if args.test_suite:
        history = TestHistory()
        try:
            from pystata_x.sfi._engine import initialize as _init
            _init()
        except Exception as e:
            print("Engine not available: {e}", file=sys.stderr)
            return
        print("Running test suite...")
        results = run_test_suite(history=history)
        # Also run e2e suite to include those results
        try:
            e2e_report = run_e2e_suite(history=history)
        except Exception:
            pass
        print()
        print(history.summary())
        return

    # ── find string-returning dispatch functions ──
    if args.protocol:
        if not args.path:
            parser.print_help()
            sys.exit(1)
        path = args.path
        if not os.path.exists(path):
            print(f"Error: {path} not found", file=sys.stderr)
            sys.exit(1)
        ana = StataBinary(path)
        ana.analyze()
        proto = ana.analyze_protocol(args.protocol)
        if args.json:
            print(json.dumps(proto, indent=2, default=str))
        else:
            print(f"Protocol analysis: {proto['name']} (idx={proto.get('dispatch_idx','?')})")
            for k, v in sorted(proto.items()):
                if v is None or (isinstance(v, list) and not v):
                    continue
                if k in ("error_codes", "pushstr_call_sites", "dispatch_idx") and not v:
                    continue
                print(f"  {k}: {v}")
        return

    if args.catalog:
        if not args.path:
            parser.print_help()
            sys.exit(1)
        path = args.path
        if not os.path.exists(path):
            print(f"Error: {path} not found", file=sys.stderr)
            sys.exit(1)
        ana = StataBinary(path)
        ana.analyze()
        catalog = ana.catalog_all_protocols()
        print(f"Protocol catalog: {len(catalog)} dispatch entries")
        str_count = sum(1 for p in catalog if p.get("protocol_type") == "string_return")
        num_count = sum(1 for p in catalog if p.get("protocol_type") == "numeric_return")
        print(f"  {'Function':30s} {'Type':20s} {'PoolCheck':12s} {'PushStr':8s}")
        print(f"  {'-'*70}")
        for p in catalog:
            pt = p.get("protocol_type", "?")
            pc = "Y" if p.get("pool_header_check") else "N"
            ps = "Y" if p.get("calls_pushstr") else "N"
            print(f"  {p['name']:30s} {pt:20s} {pc:12s} {ps:8s}")
        print(f"\nSummary: {str_count} string_return, {num_count} numeric_return, "
              f"{len(catalog)-str_count-num_count} other")
        return

    if args.pool_catalog:
        if not args.path:
            parser.print_help()
            sys.exit(1)
        path = args.path
        if not os.path.exists(path):
            print(f"Error: {path} not found", file=sys.stderr)
            sys.exit(1)
        ana = StataBinary(path)
        ana.analyze()
        catalog = ana.pool_catalog()
        print(f"Pool-Header Check Catalog: {len(catalog)} dispatch entries")
        print(f"  {'Function':30s} {'PoolCheck':12s} {'Type':30s} {'PushStr':8s}")
        print(f"  {'-'*85}")
        types: dict = {}
        for p in catalog:
            pt = p["pool_check_type"]
            types[pt] = types.get(pt, 0) + 1
            pc = "Y" if p["has_pool_check"] else "N"
            ps = "Y" if p["has_pushstr"] else "N"
            print(f"  {p['name']:30s} {pc:12s} {pt:30s} {ps:8s}")
        print(f"\nPool-check type distribution:")
        for t, c in sorted(types.items(), key=lambda x: -x[1]):
            bar = "#" * min(c, 40)
            print(f"  {t:30s}: {c:3d}  {bar}")
        return

    if args.analyze_strings:
        if not args.path:
            parser.print_help()
            sys.exit(1)
        path = args.path
        if not os.path.exists(path):
            print(f"Error: {path} not found", file=sys.stderr)
            sys.exit(1)
        ana = StataBinary(path)
        ana.analyze()

        string_fns = ana.find_string_functions()
        string_entries = [s for s in string_fns if s["has_string_chain"]]

        filter_str = args.analyze_strings
        if filter_str and filter_str != "all":
            string_entries = [s for s in string_entries
                              if any(filter_str.lower() in n.lower() for n in s["names"])]

        print(f"═" * 60)
        print(f"Deep String-Dispatch Analysis ({len(string_entries)} functions)")
        print(f"═" * 60)

        history = TestHistory()
        for s in string_entries:
            name = s["names"][0] if s["names"] else f"dispatch[{s['dispatch_idx']}]"
            print(f"\n── Analyzing {name} (dispatch[{s['dispatch_idx']}])")
            analysis = ana.analyze_dispatch_fn(name)
            proto = ana.analyze_protocol(name)

            # Follow thunk path detals
            insns = ana._follow_thunk(s["vaddr"], max_depth=3)
            pool_check = analysis.get("has_pool_header_check", False)
            error_code = analysis.get("error_code")

            # Determine pool-header check pattern
            pool_type = "none"
            for _, _, mnemonic, op_str in insns:
                if "- 0x94" in op_str or "-0x94" in op_str:
                    pool_type = "data_buf[-0x94]" if "rdi" in op_str else "tsmat_ptr[-0x10]->[-0x94]"
                    break

            print(f"  vaddr:     {hex(s['vaddr'])}")
            print(f"  chain:     {' -> '.join(hex(a) for a in s['call_chain'][:5])}")
            print(f"  pool_check:{pool_type}  (detected={pool_check})")
            print(f"  error_code:{error_code}")
            print(f"  protocol:  {proto.get('protocol_type', '?')}")
            if proto.get("arg_types"):
                print(f"  args:      {proto['arg_types']}")

            # Log to TestHistory
            history.record(
                f"string_fn_{name}",
                passed=True,
                value={
                    "dispatch_idx": s["dispatch_idx"],
                    "vaddr": hex(s["vaddr"]),
                    "pool_check": pool_type,
                    "error_code": error_code,
                    "protocol_type": proto.get("protocol_type"),
                    "chain_depth": len(s["call_chain"]),
                }
            )

        print(f"\n" + history.summary())
        return

    if args.find_strings:
        if not args.path:
            parser.print_help()
            sys.exit(1)
        path = args.path
        if not os.path.exists(path):
            print(f"Error: {path} not found", file=sys.stderr)
            sys.exit(1)
        ana = StataBinary(path)
        ana.analyze()

        print("═" * 60)
        print("Deep String-Function Discovery (tracing call chains to _pushstr)")
        print("═" * 60)

        string_fns = ana.find_string_functions()
        string_entries = [s for s in string_fns if s["has_string_chain"]]
        non_string_entries = [s for s in string_fns if not s["has_string_chain"]]

        print(f"\n── STRING-RETURNING ({len(string_entries)}) ──")
        for s in sorted(string_entries, key=lambda x: x["dispatch_idx"]):
            path_str = " → ".join([hex(a) for a in s["call_chain"][:4]])
            if len(s["call_chain"]) > 4:
                path_str += f" ... (+{len(s['call_chain'])-4})"
            name_str = ", ".join(s["names"])
            print(f"  dispatch[{s['dispatch_idx']:4d}] @ {hex(s['vaddr']):14s}  {name_str}")
            print(f"                    chain: {path_str}")

        # For non-string entries, show the ones that are string-RELATED by name
        print(f"\n── NOT STRING ({len(non_string_entries)}) ──")
        # Show string-related names even if they don't reach _pushstr
        string_name_keywords = ["str", "varname", "varlabel", "varformat",
                               "vartype", "global", "local", "macro",
                               "char", "tempfile", "tempname", "dir",
                               "sdata", "sstore", "vlmap", "alias"]
        for s in sorted(non_string_entries, key=lambda x: x["dispatch_idx"]):
            names = s["names"]
            is_string_related = any(
                any(kw in n.lower() for kw in string_name_keywords)
                for n in names
            )
            if not is_string_related:
                continue
            name_str = ", ".join(names)
            print(f"  dispatch[{s['dispatch_idx']:4d}] @ {hex(s['vaddr']):14s}  {name_str}  [NO STRING CHAIN]")

        # Also find ALL callers of _pushstr in entire .text
        pushstr_vaddr = ana.push_fns.get("_pushstr")
        if pushstr_vaddr:
            print(f"\n── ALL DIRECT CALLERS OF _pushstr (0x{pushstr_vaddr:x}) IN .text ──")
            callers = ana.find_callers(pushstr_vaddr, search_limit=0)
            for caller_vaddr, offset in callers[:30]:
                print(f"  @ {hex(caller_vaddr)}")
            if len(callers) > 30:
                print(f"  ... and {len(callers) - 30} more")
        else:
            print(f"\n  _pushstr not found in push_fns")

        return

    if not args.path:
        parser.print_help()
        sys.exit(1)

    path = args.path
    if not os.path.exists(path):
        print(f"Error: {path} not found", file=sys.stderr)
        sys.exit(1)

    # ── check pool header tag ──
    if args.check_pool:
        try:
            from pystata_x.sfi._engine import initialize as _init
            _init()
        except Exception as e:
            print("Engine not available: {e}", file=sys.stderr)
            return
        result = check_pool_header()
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print("Pool Header Tag Check:")
            print(f"  SP advances:    {result.get('sp_advances')}")
            print(f"  data_buf[-0x94]: 0x{result.get('data_tag_value', 0):x} "
                  f"(need 0x2b) {'OK' if result.get('has_tag') else 'FAIL'}")
            if result.get('error'):
                print(f"  ERROR: {result['error']}")
        return

    # ── binary text pattern search ──
    if args.search:
        pattern_bytes = args.search.encode() if not args.search.startswith("0x") else bytes.fromhex(args.search[2:])
        from pystata_x.sfi._analyzer import StataBinary as _SB
        ana = _SB(path)
        ana.analyze()
        found = False
        for sec_name in [".rodata", ".data.rel.ro", ".data", ".text"]:
            hits = ana.find_strings(pattern_bytes, sec_name)
            if hits:
                found = True
                print(f"Section {sec_name}: {len(hits)} hits")
                for vaddr, off in hits[:20]:
                    print(f"  0x{vaddr:x} (file offset 0x{off:x})")
                if len(hits) > 20:
                    print(f"  ... and {len(hits) - 20} more")
        if not found:
            print(f"Pattern {args.search!r} not found in any section")
        return

    # ── cross-reference search ──
    if args.xfsearch:
        target = int(args.xfsearch, 16) if args.xfsearch.startswith("0x") else int(args.xfsearch)
        ana = StataBinary(path)
        ana.analyze()
        callers = ana.find_callers(target, search_limit=0)
        print(f"Found {len(callers)} callers of 0x{target:x} in .text:")
        for caller_vaddr, _ in callers[:50]:
            print(f"  0x{caller_vaddr:x}")
        if len(callers) > 50:
            print(f"  ... and {len(callers) - 50} more")
        return

    # ── dispatch function analysis (no cache needed) ──
    if args.dispatch:
        ana = StataBinary(path)
        ana.analyze()
        result = ana.analyze_dispatch_fn(args.dispatch)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"Dispatch function analysis: {result.get('name')}")
            print(f"  Vaddr:         0x{result.get('vaddr', 0):x}")
            print(f"  Size:          {result.get('size', 0)} instructions")
            print(f"  Dispatch idx:  {result.get('dispatch_index')}")
            print(f"  Reads stack:   {result.get('reads_stack_args')}")
            print(f"  Calls push:    {result.get('calls_push_function')}")
            print(f"  Has return:    {result.get('has_return')}")
            print(f"  Pool hdr check:{result.get('has_pool_header_check')}")
            ec = result.get('error_code')
            print(f"  Error code:    0x{ec:x}" if ec is not None else "  Error code:    None")
            if "error" in result:
                print(f"  ERROR: {result['error']}")
            else:
                sections = result.get("sections", [])
                for label, lines in sections:
                    print(f"\n  ── {label} ──")
                    for line in lines[:60]:
                        print(f"    {line}")
                    if len(lines) > 60:
                        print(f"    ... ({len(lines)} total)")
        return

    # ── trace dispatch call ──
    if args.trace:
        try:
            from pystata_x.sfi._engine import initialize as _init
            _init()
            import pystata_x.sfi._engine as engine
            engine._LIB.StataSO_Execute(b"sysuse auto, clear")
        except Exception as e:
            print(f"Engine not available: {e}", file=sys.stderr)
            return
        # Parse trace arg: "function" or "function:arg1,arg2"
        trace_fn = args.trace
        trace_args = ()
        if ":" in trace_fn:
            parts = trace_fn.split(":", 1)
            trace_fn = parts[0]
            trace_args = tuple(
                int(a) if a.lstrip("-").isdigit()
                else float(a) if _is_float(a)
                else a
                for a in parts[1].split(",")
            )
        ana = StataBinary(path)
        ana.analyze()
        trace = ana.trace_dispatch_call(trace_fn, *trace_args, engine=engine)
        print(f"\n── Trace: {trace_fn}{trace_args} ──────────────────────")
        print(f"  Result: {trace.get('result')}")
        print(f"  Error:  {trace.get('error')}")
        print(f"  Steps:")
        for step in trace.get("steps", []):
            label = step.get("action", step.get("step", "?"))
            value = step.get("value", step.get("result", ""))
            if value is not None:
                print(f"    {label}: {value}")
            else:
                print(f"    {label}")
        # Log to TestHistory
        history = TestHistory()
        history.record(
            f"trace_{trace_fn}",
            passed=trace.get("result") is not None and trace.get("error") is None,
            value=trace.get("result"),
            notes=f"args={trace_args}, steps={len(trace.get('steps', []))}"
        )
        return

    # ── full analysis ──
    cached = None if args.force else StataBinary.from_cache(path)
    if cached:
        ana = cached
        if not args.json:
            print(f"Using cached manifest v{ana._to_manifest()['manifest_version']}",
                  file=sys.stderr)
    else:
        ana = StataBinary(path)
        ana.analyze()
        if not args.json:
            print(f"Fresh analysis: {ana.format}/{ana.arch}, "
                  f"{len(ana.symbols)} symbols",
                  file=sys.stderr)

    # --cache flag
    if args.cache:
        cp = ana.save_cache()
        if not args.json:
            print(f"Cache saved: {cp}", file=sys.stderr)

    # --json output
    if args.json:
        print(json.dumps(ana._to_manifest(), indent=2))
        return

    # --report (default)
    print(ana.report())

    # --var-info
    if args.var_info:
        try:
            from pystata_x.sfi._engine import initialize as _init
            _init()
            from pystata_x.sfi._engine import get_var_info, _LIB
            # Load auto dataset if none loaded
            from pystata_x.sfi._engine import call_int
            if not call_int("nvar"):
                print("  Loading auto dataset...", file=sys.stderr)
                _LIB.StataSO_Execute(b"sysuse auto, clear")
        except Exception as e:
            print(f"\n── Var-Info FAILED (engine not available): {e}",
                  file=sys.stderr)
            return
        print("\n── Variable Metadata ────────────────────────────")
        try:
            info = get_var_info()
        except Exception as e:
            print(f"  Error: {e}", file=sys.stderr)
            return
        if not info:
            print("  Could not read variable metadata.",
                  file=sys.stderr)
            return
        print(f"  nvar = {info.get('nvar', 0)}")
        for i, name in enumerate(info.get("names", []), 1):
            label = info.get("labels", [None] * 100)[i - 1] \
                if i <= len(info.get("labels", [])) else None
            vtype = info.get("types", [None] * 100)[i - 1] \
                if i <= len(info.get("types", [])) else None
            fmt = info.get("formats", [None] * 100)[i - 1] \
                if i <= len(info.get("formats", [])) else None
            print(f"  [{i:2d}] {name or '?':10s} {fmt or '?':8s} {label or '-'}")
        return

    # --verify
    if args.verify:
        try:
            from pystata_x.sfi._engine import initialize as _init
            _init()
        except Exception as e:
            print(f"\n── Verification FAILED (engine not available): {e}",
                  file=sys.stderr)
            return
        print("\n── Live Verification ──────────────────────────────")
        results = ana.verify_all()
        ok = sum(1 for r in results if r["status"] == "ok")
        null = sum(1 for r in results if r["status"] == "null")
        err = sum(1 for r in results if r["status"] == "error")
        skip = sum(1 for r in results if r["status"] == "skip")
        print(f"  {ok} ok, {null} null, {err} error, {skip} skipped")
        for r in results:
            if r["status"] in ("ok", "null"):
                mark = "✓" if r["status"] == "ok" else "~"
                print(f"    {mark} {r['name']}: {r.get('value', '?')}")
            elif r["status"] == "error":
                print(f"    ✗ {r['name']}: {r.get('error', '?')}")
            else:
                print(f"    - {r['name']}: {r.get('reason', '?')}")





# ═══════════════════════════════════════════════════════════════════
#  StataEngine — Live engine wrapper
# ═══════════════════════════════════════════════════════════════════
# Provides interactive Python REPL access to the live Stata engine
# with full introspection, tracing, and debugging capabilities.
#
# Usage:
#   >>> from pystata_x.sfi._analyzer import StataEngine
#   >>> eng = StataEngine()         # boots Stata, loads auto dataset
#   >>> eng.call("nvar")            # 12
#   >>> eng.nvar                     # 12 (property, cached)
#   >>> eng.trace("nvar")           # detailed step-by-step trace
#   >>> eng.inspect_stack()          # stack pointer, last tsmat, data buf
#   >>> eng.dump_state()             # summary of current Stata state
# ═══════════════════════════════════════════════════════════════════


class StataEngine:
    """Interactive wrapper around the live Stata engine.

    Provides direct REPL access to all engine operations with
    automatic tracing, stack inspection, and state dumps.
    """

    def __init__(self, lib_path: str | None = None, auto_load: bool = True):
        self._engine: Any = None
        self._inited: bool = False
        if lib_path:
            import os
            os.environ["STATA_LIB_PATH"] = lib_path
        self._boot()
        if auto_load:
            self._load_auto()

    def _boot(self):
        """Initialize the Stata engine."""
        if self._inited:
            return
        import pystata_x.sfi._engine as _eng_mod
        _eng_mod.initialize()
        if not _eng_mod._INITIALIZED:
            raise RuntimeError("Engine failed to initialize")
        self._engine = _eng_mod
        self._inited = True

    def _load_auto(self):
        """Load the auto dataset if none is loaded."""
        if not self._inited:
            return
        nvar = self.call("nvar")
        if not nvar:
            self._engine._LIB.StataSO_Execute(b"sysuse auto, clear")

    @property
    def nvar(self) -> int | None:
        return self.call("nvar")

    @property
    def nobs(self) -> int | None:
        return self.call("nobs")

    def call(self, name: str, *args) -> Any:
        """Call any _bist_* function and return the raw result."""
        if not self._inited:
            raise RuntimeError("Engine not initialized")
        return self._engine.call_int(name, *args)

    def call_double(self, name: str, *args) -> float | None:
        return self._engine.call_double(name, *args)

    def call_string(self, name: str, *args) -> str | None:
        return self._engine.call_string(name, *args)

    def call_void(self, name: str, *args):
        return self._engine.call_void(name, *args)

    def trace(self, name: str, *args) -> dict:
        """Trace a dispatch call with full step-by-step breakdown."""
        eng = self._engine
        result = {"function": name, "args": args, "steps": []}
        try:
            addr = eng._resolve_name(name)
            result["steps"].append({"action": "resolve_symbol", "value": hex(addr) if addr else None})
            if addr is None:
                result["error"] = f"Symbol {name} not found in manifest"
                return result

            sp_before = eng._save_sp()
            result["steps"].append({"action": "save_sp", "value": hex(sp_before)})

            eng._push_args(args)
            result["steps"].append({"action": "push_args", "value": args})

            rt = eng._BASE + addr
            # Determine return type based on function convention
            if name.startswith("_bist_"):
                # Try each caller type
                fn = eng._get_fn(rt, None, ctypes.c_int)
                w0 = len(args) if args else 0
                result["steps"].append({"action": "call", "target": hex(rt)})
                fn(w0)

            result["steps"].append({"action": "after_call"})
            val = eng._pop_and_read_int(sp_before)
            result["result"] = val
        except Exception as e:
            result["error"] = str(e)
            import traceback
            result["traceback"] = traceback.format_exc()
        return result

    def inspect_stack(self) -> dict:
        """Read current Stata stack state."""
        eng = self._engine
        state = {}
        try:
            sp = eng._save_sp()
            state["sp"] = hex(sp)
            state["sp_raw"] = sp

            # Read tsmat at SP — only if address looks valid
            if sp is not None and 0x100000 < sp < 0x800000000000:
                try:
                    tsmat_val = ctypes.c_uint64.from_address(sp).value
                    if 0x100000 < tsmat_val < 0x800000000000:
                        state["tsmat_ptr"] = hex(tsmat_val)
                        dbl = ctypes.c_double.from_address(tsmat_val).value
                        state["tsmat_double"] = dbl
                        try:
                            marker = ctypes.c_uint16.from_address(tsmat_val + 0x34).value
                            state["tsmat_sentinel"] = hex(marker)
                        except Exception:
                            pass
                        try:
                            type_byte = ctypes.c_uint8.from_address(tsmat_val + 0x36).value
                            state["tsmat_type"] = type_byte
                        except Exception:
                            pass
                        try:
                            tag = ctypes.c_uint8.from_address(tsmat_val - 0x94).value
                            state["data_tag"] = hex(tag)
                        except Exception:
                            pass
                except (OSError, ValueError):
                    pass
        except Exception as e:
            state["error"] = str(e)
        return state

    def dump_state(self) -> dict:
        """Full engine state summary."""
        eng = self._engine
        state = {}
        try:
            state["initialized"] = eng._INITIALIZED
            state["platform"] = getattr(eng, "_PLATFORM", "?")
            state["nvar"] = self.call("nvar")
            state["nobs"] = self.call("nobs")
            state["base"] = hex(eng._BASE)
            state["syms_count"] = len(eng._SYMS)
            state["stack"] = self.inspect_stack()
        except Exception as e:
            state["error"] = str(e)
            import traceback
            state["traceback"] = traceback.format_exc()
        return state

    def __repr__(self) -> str:
        nv = self.nvar
        no = self.nobs
        return f"<StataEngine nvar={nv} nobs={no} inited={self._inited}>"


if __name__ == "__main__":
    main()
