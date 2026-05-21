"""ELF binary section reader — pure ctypes, no Capstone needed.

Reads ELF64 section headers and provides convenient access to section
data and virtual-address lookups.
"""

import struct
from pathlib import Path
from typing import Optional


class ELFReader:
    """Minimal ELF64 reader that extracts section data by name.

    Usage::

        elf = ELFReader("/path/to/libstata.so")
        text_raw = elf.text_raw           # .text bytes
        data_raw = elf.raw_of(".data")    # any section by name
        vaddr = elf.section_addr(".text") # virtual address of section

    All data is read from the file; no runtime memory needed.
    """

    def __init__(self, path: str):
        self.path = path
        self._raw: Optional[bytes] = None
        self._sections: dict[str, dict] = {}
        self._arch: Optional[str] = None

    # ── Public properties ───────────────────────────────────────────

    @property
    def raw(self) -> bytes:
        """Full file contents as bytes."""
        if self._raw is None:
            with open(self.path, "rb") as f:
                self._raw = f.read()
        return self._raw

    @property
    def sections(self) -> dict[str, dict]:
        """dict[section_name] -> {offset, size, addr, ...}."""
        if not self._sections:
            self._parse()
        return dict(self._sections)

    @property
    def text_raw(self) -> bytes:
        "Raw bytes of .text section."
        sec = self.sections.get(".text")
        if not sec:
            return b""
        return self.raw[sec["offset"]:sec["offset"] + sec["size"]]

    @property
    def text_vaddr(self) -> int:
        "Virtual address of .text section."
        sec = self.sections.get(".text")
        return sec["addr"] if sec else 0

    @property
    def arch(self) -> str:
        "Detected architecture: 'x86_64' or 'arm64'."
        if self._arch is None:
            self._detect_arch()
        return self._arch or "unknown"

    # ── Public methods ──────────────────────────────────────────────

    def raw_of(self, name: str) -> bytes:
        """Return raw bytes for a section by name."""
        sec = self.sections.get(name)
        if not sec:
            return b""
        if sec["type"] == 0x08:  # SHT_NOBITS — no file data
            return b""
        return self.raw[sec["offset"]:sec["offset"] + sec["size"]]

    def section_addr(self, name: str) -> int:
        """Return virtual base address for a section."""
        sec = self.sections.get(name)
        return sec["addr"] if sec else 0

    def section_offset(self, name: str) -> int:
        """Return file offset for a section."""
        sec = self.sections.get(name)
        return sec["offset"] if sec else 0

    # ── Internal ────────────────────────────────────────────────────

    def _parse(self) -> None:
        """Parse ELF64 section headers and populate self._sections."""
        data = self.raw
        if len(data) < 64:
            return

        # ELF64 header
        e_shoff = struct.unpack_from("<Q", data, 0x28)[0]   # section header offset
        e_shentsize = struct.unpack_from("<H", data, 0x3A)[0]  # section header entry size
        e_shnum = struct.unpack_from("<H", data, 0x3C)[0]       # number of sections
        e_shstrndx = struct.unpack_from("<H", data, 0x3E)[0]    # .shstrtab index

        if e_shentsize == 0 or e_shnum == 0:
            return

        shstrtab_off = e_shoff + e_shstrndx * e_shentsize
        sh_name_off = struct.unpack_from("<I", data, shstrtab_off + 0x18)[0]
        sh_name_size = struct.unpack_from("<Q", data, shstrtab_off + 0x20)[0]
        names = data[sh_name_off:sh_name_off + sh_name_size]

        for i in range(e_shnum):
            off = e_shoff + i * e_shentsize
            sh_name_idx = struct.unpack_from("<I", data, off + 0x00)[0]
            sh_type = struct.unpack_from("<I", data, off + 0x04)[0]
            sh_flags = struct.unpack_from("<Q", data, off + 0x08)[0]
            sh_addr = struct.unpack_from("<Q", data, off + 0x10)[0]
            sh_offset = struct.unpack_from("<Q", data, off + 0x18)[0]
            sh_size = struct.unpack_from("<Q", data, off + 0x20)[0]

            if sh_type == 0x08:  # SHT_NOBITS (e.g. .bss) — no file data
                pass  # preserve size, but raw_of will return b""

            name = self._cstr_at(names, sh_name_idx)
            self._sections[name] = {
                "offset": sh_offset,
                "size": sh_size,
                "addr": sh_addr,
                "flags": sh_flags,
                "type": sh_type,
            }

    def _detect_arch(self) -> None:
        """Detect architecture from ELF header e_machine field."""
        data = self.raw
        if len(data) < 20:
            self._arch = "unknown"
            return
        e_machine = struct.unpack_from("<H", data, 0x12)[0]
        if e_machine == 0x3E:   # EM_X86_64
            self._arch = "x86_64"
        elif e_machine == 0xB7:  # EM_AARCH64
            self._arch = "arm64"
        else:
            self._arch = f"machine_{e_machine:#x}"

    @staticmethod
    def _cstr_at(buf: bytes, start: int) -> str:
        """Read null-terminated string at *start*."""
        end = buf.find(b"\0", start)
        if end < 0:
            return buf[start:].decode("ascii", errors="replace")
        return buf[start:end].decode("ascii", errors="replace")
