"""Unit tests for pystata-analyzer ELF reader and binary analysis."""

import os
import sys
import tempfile
from pathlib import Path

# Add the package to path for testing
HERE = Path(__file__).resolve().parent
PKG_DIR = HERE.parent / "src"
sys.path.insert(0, str(PKG_DIR))

from pystata_analyzer import ELFReader, StataBinary, HAS_CAPSTONE


# ── Minimal ELF64 test fixture ───────────────────────────────────

def _make_minimal_elf() -> bytes:
    """Create a minimal valid ELF64 binary for testing.

    Has .text, .data, .bss sections with enough structure to test
    section parsing and dispatch-table discovery.
    """
    import struct

    # ELF64 header (64 bytes)
    ident = b"\x7fELF" + b"\x02\x01\x01\x00" + b"\x00" * 8
    e_type = 3  # ET_DYN
    e_machine = 0x3E  # EM_X86_64
    e_version = 1
    e_entry = 0
    e_phoff = 0  # No program headers for this test
    e_shoff = 64  # Section headers start after ELF header
    e_flags = 0
    e_ehsize = 64
    e_phentsize = 0
    e_phnum = 0
    e_shentsize = 64
    e_shnum = 5  # null + .shstrtab + .text + .data + .bss
    e_shstrndx = 1

    header = struct.pack(
        "<16sHHIQQQIHHHHHH",
        ident, e_type, e_machine, e_version, e_entry,
        e_phoff, e_shoff, e_flags, e_ehsize,
        e_phentsize, e_phnum, e_shentsize, e_shnum, e_shstrndx,
    )

    # Section header table (4 entries at offset 64, each 64 bytes)
    # Entry 0 is always null
    # Entry 1: .shstrtab
    # Entry 2: .text
    # Entry 3: .data (also covers .bss via SHT_NOBITS)

    shstrtab_data = b"\x00.shstrtab\x00.text\x00.data\x00.bss\x00"
    shstrtab_off = 64 + 5 * 64  # ELF header + all section headers
    shstrtab_size = len(shstrtab_data)
    text_data = b"\xcc" * 64
    text_off = shstrtab_off + shstrtab_size
    data_data = b"\x00" * 64
    data_off = text_off + len(text_data)
    bss_off = data_off + len(data_data)  # .bss is SHT_NOBITS, no file data

    def _sh_entry(name_idx, stype, sflags, saddr, soff, ssize):
        # ELF64 section header: sh_name(4) + sh_type(4) + sh_flags(8) +
        # sh_addr(8) + sh_offset(8) + sh_size(8) + sh_link(4) +
        # sh_info(4) + sh_addralign(8) + sh_entsize(8) = 64 bytes
        return struct.pack(
            "<IIQQQQIIQQ",
            name_idx, stype, sflags,
            saddr, soff, ssize,
            0, 0,  # sh_link, sh_info
            16, 0,  # sh_addralign, sh_entsize
        )

    sh_entries = [
        struct.pack("<64x"),  # null entry (empty)
        _sh_entry(1, 3, 0, 0, shstrtab_off, shstrtab_size),  # .shstrtab
        _sh_entry(11, 1, 6, 0x400000, text_off, len(text_data)),  # .text
        _sh_entry(17, 1, 3, 0x500000, data_off, len(data_data)),  # .data
        _sh_entry(23, 8, 3, 0x600000, 0, 256),  # .bss (SHT_NOBITS)
    ]

    sections_bytes = b"".join(sh_entries)
    return header + sections_bytes + shstrtab_data + b"\xcc" * 64 + b"\x00" * 64


# ── Tests ────────────────────────────────────────────────────────

class TestELFReader:
    def test_detect_x86_64(self):
        elf_data = _make_minimal_elf()
        with tempfile.NamedTemporaryFile(delete=False, suffix=".so") as f:
            f.write(elf_data)
            tmp = f.name
        try:
            elf = ELFReader(tmp)
            assert elf.arch == "x86_64"
        finally:
            os.unlink(tmp)

    def test_section_names(self):
        elf_data = _make_minimal_elf()
        with tempfile.NamedTemporaryFile(delete=False, suffix=".so") as f:
            f.write(elf_data)
            tmp = f.name
        try:
            elf = ELFReader(tmp)
            sections = elf.sections
            assert ".text" in sections
            assert ".data" in sections
            assert ".bss" in sections
        finally:
            os.unlink(tmp)

    def test_text_raw(self):
        elf_data = _make_minimal_elf()
        with tempfile.NamedTemporaryFile(delete=False, suffix=".so") as f:
            f.write(elf_data)
            tmp = f.name
        try:
            elf = ELFReader(tmp)
            raw = elf.text_raw
            assert len(raw) == 64
            assert raw == b"\xcc" * 64
        finally:
            os.unlink(tmp)


class TestStataBinary:
    def test_instantiate(self):
        # Can instantiate without a real binary (analysis will fail gracefully)
        b = StataBinary("/nonexistent/path")
        assert b.path == "/nonexistent/path"
        assert not b._analyzed

    def test_sha256_of_nonexistent(self):
        b = StataBinary("/nonexistent/path")
        try:
            _ = b.sha256
            assert False, "Should have raised FileNotFoundError"
        except FileNotFoundError:
            pass

    def test_dispatch_entries_empty_initially(self):
        b = StataBinary("/nonexistent")
        assert b.dispatch_entries == []


class TestProtocolAnalysis:
    def test_analyze_protocol_no_binary(self):
        b = StataBinary("/nonexistent")
        result = b.analyze_protocol("_bist_nobs")
        assert "error" in result

    def test_analyze_dispatch_fn_no_binary(self):
        b = StataBinary("/nonexistent")
        result = b.analyze_dispatch_fn("_bist_nobs")
        assert "error" in result

    def test_trace_error_codes_no_binary(self):
        b = StataBinary("/nonexistent")
        result = b.trace_error_codes(0x1000)
        assert result == []

    def test_trace_entry_points_no_binary(self):
        b = StataBinary("/nonexistent")
        result = b.trace_entry_points("_bist_nobs")
        assert len(result) == 0
