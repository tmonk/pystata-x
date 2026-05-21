"""Integration tests for pystata-analyzer against the real Stata binary.

These tests require the actual libstata-se.so from a Stata installation
and are only run inside the Docker container where Stata is available.
"""

import os
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
PKG_DIR = HERE.parent / "src"
sys.path.insert(0, str(PKG_DIR))

from pystata_analyzer import StataBinary

# Detect if we're in a Stata-capable environment
LIB_CANDIDATES = [
    "/usr/local/stata19/libstata-se.so",
    "/usr/local/stata19/libstata.so",
    os.environ.get("STATA_LIB_PATH", ""),
]

STATA_LIB = None
for p in LIB_CANDIDATES:
    if p and os.path.exists(p):
        STATA_LIB = p
        break

requires_stata = pytest.mark.skipif(
    STATA_LIB is None,
    reason="Stata shared library not found — try setting STATA_LIB_PATH",
)


class TestBinaryAnalysisIntegration:
    """End-to-end analysis against a real Stata binary."""

    @requires_stata
    def test_elf_loading(self):
        b = StataBinary(STATA_LIB)
        b.analyze()
        assert b._elf is not None
        assert b.arch == "x86_64"
        assert ".text" in b._elf.sections
        assert ".data" in b._elf.sections
        assert b._elf.text_vaddr > 0
        assert len(b._elf.text_raw) > 1000000  # >1MB of code

    @requires_stata
    def test_dispatch_table(self):
        b = StataBinary(STATA_LIB)
        b.analyze()
        assert len(b.dispatch_entries) >= 1500  # typically 1686
        assert all(e > 0 for e in b.dispatch_entries[:100])

    @requires_stata
    def test_st_entries(self):
        b = StataBinary(STATA_LIB)
        b.analyze()
        assert len(b.st_entries) >= 100  # typically 118
        names = [name for _, name, _ in b.st_entries]
        assert "st_data" in names
        assert "st_nobs" in names
        assert "st_nvar" in names
        assert "st_global" in names

    @requires_stata
    def test_symbols(self):
        b = StataBinary(STATA_LIB)
        b.analyze()
        assert len(b.symbols) >= 100
        for key in ["_bist_data", "_bist_nobs", "_bist_nvar", "_bist_global"]:
            assert key in b.symbols, f"Missing symbol: {key}"
            assert b.symbols[key] > 0

    @requires_stata
    def test_push_functions(self):
        b = StataBinary(STATA_LIB)
        b.analyze()
        # At minimum, _pushdbl and _pushstr should be found
        assert "_pushdbl" in b.push_fns
        assert "_pushstr" in b.push_fns
        for name, addr in b.push_fns.items():
            assert addr > 0, f"Push function {name} has invalid address"

    @requires_stata
    def test_stack_ptr(self):
        b = StataBinary(STATA_LIB)
        b.analyze()
        assert b.stack_ptr_vaddr > 0
        # Stack pointer should be in the .bss region (address >= 0x500000)
        assert b.stack_ptr_vaddr >= 0x500000, \
            f"stack_ptr_vaddr 0x{b.stack_ptr_vaddr:x} below .bss region"

    @requires_stata
    def test_protocol_analysis_data(self):
        b = StataBinary(STATA_LIB)
        b.analyze()
        proto = b.analyze_full_protocol("_bist_data")
        assert proto["uses_push_stack"] is True
        assert proto["protocol_type"] == "read_write"
        assert proto["dispatch_index"] == 87
        assert len(proto.get("arg_ptr_reads", [])) > 0
        assert len(proto.get("edi_checks", [])) > 0
        assert len(proto.get("entry_candidates", [])) > 0

    @requires_stata
    def test_protocol_analysis_global(self):
        b = StataBinary(STATA_LIB)
        b.analyze()
        proto = b.analyze_full_protocol("_bist_global")
        assert proto["uses_push_stack"] is True
        assert proto["dispatch_index"] == 1314
        assert len(proto.get("pushstr_calls", [])) > 0  # reads globals via _pushstr

    @requires_stata
    def test_protocol_analysis_numscalar(self):
        b = StataBinary(STATA_LIB)
        b.analyze()
        proto = b.analyze_full_protocol("_bist_numscalar")
        # numscalar checks edi == 1 (single arg)
        checks = [e["checks"] for e in proto.get("edi_checks", [])]
        assert 1 in checks

    @requires_stata
    def test_entry_points_data(self):
        b = StataBinary(STATA_LIB)
        b.analyze()
        eps = b.trace_entry_points("_bist_data")
        assert len(eps) >= 2  # at least read + write entries
        types = [ep["type"] for ep in eps]
        assert "push_prologue" in types  # 6-push write entry

    @requires_stata
    def test_error_codes_data(self):
        b = StataBinary(STATA_LIB)
        b.analyze()
        codes = b.trace_error_codes(b.symbols["_bist_data"], max_size=4096)
        assert len(codes) >= 10
        known = {c["error_code"] for c in codes}
        # Should have at least some of these: 0xc1e (3102), 0xc1f (3103), 0xc84 (3204)
        common = known & {0xc1e, 0xc1f, 0xc84, 0xcb7, 0xc82, 0xce4}
        assert len(common) >= 2

    @requires_stata
    def test_manifest(self):
        b = StataBinary(STATA_LIB)
        mdata = b.analyze()
        assert mdata["sha256"] == b.sha256
        assert mdata["n_bist_symbols"] == len(b.symbols)
        assert "symbols" in mdata
        assert "data_offsets" in mdata
        assert "push_fns" in mdata

    @requires_stata
    def test_cache_save_load(self):
        import tempfile, json
        b = StataBinary(STATA_LIB)
        b.analyze()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            path = f.name
            json.dump(b._to_manifest(), f)
        try:
            with open(path) as f:
                loaded = json.load(f)
            assert loaded["sha256"] == b.sha256
            assert loaded["n_bist_symbols"] > 100
        finally:
            os.unlink(path)
