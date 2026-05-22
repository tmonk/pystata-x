"""StataBinary — core analysis class for Stata shared libraries.

Takes an ELF path, loads sections via ELFReader, and provides:
- Dispatch table discovery (1686 entries on x86_64)
- st_* name table parsing (maps names → dispatch indices)
- Push function discovery (_pushstr, _pushint, _pushdbl)
- Manifest generation
- Protocol analysis for individual dispatch functions
"""

import hashlib
import json
import logging
import os
import re
import struct
import sys
from pathlib import Path
from typing import Any, Optional

from pystata_analyzer.elf import ELFReader
from pystata_analyzer.helpers import (
    HAS_CAPSTONE, _Cs, CS_ARCH_X86, CS_MODE_64,
    ARG_PTR_ADDR, SP_GLOBAL_ADDR,
    _cstr, _find_bytes, _fn_start, _fn_size,
)


# Known infrastructure globals to exclude from memory layout discovery
# These are the push+stack protocol addresses, not data tables
_INFRASTRUCTURE_ADDRS = {
    ARG_PTR_ADDR,        # 0x500C6A0 — push+stack argument pointer
    SP_GLOBAL_ADDR,      # 0x500C638 — SP-resetting global
    ARG_PTR_ADDR - 8,    # 0x500C698 — near ARG_PTR (part of same struct)
    ARG_PTR_ADDR - 0x68, # 0x500C638 — same as SP_GLOBAL
}


class StataBinary:
    """Core analysis engine for a Stata shared library binary.

    Loads an ELF (or Mach-O) shared library, discovers the dispatch table,
    st_* name table, push functions, and provides methods for deep protocol
    analysis of individual dispatch functions.

    Usage::

        b = StataBinary("/path/to/libstata.so")
        b.analyze()                     # runs all discovery
        print(b.report())               # text summary

    Architecture
    ------------
    Stata's x86_64 binary uses a triple-layer dispatch architecture:

    **1. Dispatch table** (1686 entries on x86_64 at ``0x440aac0``)
      Each entry is either a direct implementation or a ``jmp`` thunk
      that routes to the real implementation.  Entries are indexed
      sequentially (0-1685) and are discovered via ``.rela.dyn`` relocations
      against ``_bist_*`` symbols.

    **2. st_* name table** (118 entries)
      A ``.data``-resident array mapping function names (``st_nobs``,
      ``st_data``, ``st_global``, etc.) to their dispatch indices.
      The ``_bist_*`` name convention is formed by replacing ``st_`` with
      ``_bist_`` (e.g. ``st_nobs`` → ``_bist_nobs``).

    **3. Push functions** (``_pushdbl``, ``_pushint``, ``_pushstr``)
      These allocate tsmat structs on Stata's internal stack and update
      ARG_PTR.  They are the PRIMARY mechanism for passing arguments to
      dispatch functions.

    Memory model
    ------------
    - **ARG_PTR** (``0x500C6A0``, A.K.A. ``_STACK_PTR_OFFSET``):
      Push functions store tsmat pointers here and advance by 8 bytes per
      push.  ``_save_sp()`` reads the current value to locate arguments.
      Most dispatch implementations index backward from ARG_PTR to find
      their arguments.

    - **SP_global** (``0x500C638``):
      Some dispatch thunks (SP-resetting protocol) write a data-descriptor
      address here.  The implementation function reads from a global C
      struct instead of from push+stack.  Used by ``_bist_nobs``,
      ``_bist_nvar``, and similar 0-arg/1-arg scalar-return functions.

    - **tsmat structure** (temporary Stata matrix):
      Each tsmat is a pool-allocated struct with data EMBEDDED at offset 0
      (a ``double`` value or a GSO string pointer).  There is no separate
      data buffer.  Pool-header detection uses the sentinel:
      ``tsmat[-0x94] == 0x2b`` (checked by ``_check_pool_header``).
      After allocation via ``pool_alloc``, the self-pointer at
      ``tsmat[-0x10]`` must be fixed (``_patch_last_tsmat()``) because
      it points to the pool free-list, not the tsmat itself.

    Protocol patterns
    -----------------
    **Standard push+stack** (``_bist_data``, ``_bist_global``, etc.)
      Arguments are pushed via ``_push_double`` / ``_push_int`` /
      ``_push_str`` which allocates tsmat structs and updates ARG_PTR.
      The implementation reads from these tsmat structs by indexing
      backward from ARG_PTR.  This is the PRIMARY protocol for all
      data-access functions.

    **SP-resetting** (``_bist_nobs``, ``_bist_nvar``, etc.)
      The dispatch thunk writes a descriptor address into SP_global
      (``0x500C638``) and the implementation reads from a global struct.
      No push function calls are needed.  Always 0-arg or 1-arg scalar
      return.

    **Internal-global** (``_bist_store`` write path, ``_bist_sdata``)
      The implementation reads from a global struct that the thunk sets
      up from Stata internals, not from ARG_PTR.  These are write-side
      functions where the caller has already gone through a type-checking
      thunk.

    **String-return** (``_bist_macroexpand``, ``_bist_dir``)
      Similar to push+stack but the return value is a GSO string pointer
      stored in a tsmat, read via ``call_string()``.

    Multi-entry dispatch
    --------------------
    Some dispatch indices share a single implementation with multiple
    entry points.  For example, dispatch[87] serves BOTH ``_bist_data``
    (read) and ``_bist_store`` (write) on x86_64.  Three sub-entry
    points exist:

    - ``0x826494`` — 2-arg read (esi=0)
    - ``0x8264b8`` — 2-arg read (esi=1, alternative path)
    - ``0x8264dc`` — 3-arg/4-arg write (6-push prologue)

    Edge cases
    ----------
    - ``_bist_putglobal`` has **NO dispatch entry** on x86_64.  Macro
      writes require a fundamentally different approach (e.g.
      ``StataSO_Execute``, which is forbidden for data access).
    - ``_bist_global`` handles single-arg reads only via push+stack.
      Its write path (edi != 1) reads from a global struct set up by
      the thunk, not from ARG_PTR.
    - ``_bist_macroexpand`` works for reading macros.  It's the only
      reliable dispatch-path method for string values.
    """

    def __init__(self, path: str):
        self.path = path
        self._elf: Optional[ELFReader] = None
        self._sha256: Optional[str] = None
        self._dispatch_entries: list[int] = []
        self._dispatch_vaddr: int = 0
        self._st_entries: list[tuple[int, str, int]] = []  # (idx, name, flags)
        self._symbols: dict[str, int] = {}  # name → vmaddr
        self._push_fns: dict[str, int] = {}
        self._stack_ptr_vaddr: int = 0
        self._err_addr_vaddr: int = 0
        self._analyzed = False

    # ═══════════════════════════════════════════════════════════════
    # Public properties
    # ═══════════════════════════════════════════════════════════════

    @property
    def sha256(self) -> str:
        if self._sha256 is None:
            h = hashlib.sha256()
            with open(self.path, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    h.update(chunk)
            self._sha256 = h.hexdigest()
        return self._sha256

    @property
    def dispatch_entries(self) -> list[int]:
        return list(self._dispatch_entries)

    @property
    def dispatch_vaddr(self) -> int:
        return self._dispatch_vaddr

    @property
    def dispatch_count(self) -> int:
        return len(self._dispatch_entries)

    @property
    def st_entries(self) -> list[tuple[int, str, int]]:
        return list(self._st_entries)

    @property
    def symbols(self) -> dict[str, int]:
        return dict(self._symbols)

    @property
    def push_fns(self) -> dict[str, int]:
        return dict(self._push_fns)

    @property
    def stack_ptr_vaddr(self) -> int:
        return self._stack_ptr_vaddr

    @property
    def err_addr_vaddr(self) -> int:
        return self._err_addr_vaddr

    @property
    def arch(self) -> str:
        return self._elf.arch if self._elf else "unknown"

    @property
    def format(self) -> str:
        return "elf" if "libstata" in self.path else "unknown"

    # ═══════════════════════════════════════════════════════════════
    # Public API
    # ═══════════════════════════════════════════════════════════════

    def analyze(self, cache: Optional[dict] = None) -> dict:
        """Run full analysis: ELF load → dispatch → names → push fns.

        Returns manifest dict with all discovered symbols, offsets, etc.
        """
        self._elf = ELFReader(self.path)
        self._elf._parse()

        if self.arch == "x86_64":
            self._analyze_elf_x86_64()
        else:
            pass  # ARM64 analysis TBD

        self._analyzed = True
        return self._to_manifest()

    def report(self) -> str:
        """Return a human-readable analysis report."""
        if not self._analyzed:
            return "(not analyzed — call .analyze() first)"
        lines = [
            f"StataBinary: {self.path}",
            f"  SHA256: {self.sha256[:16]}…",
            f"  Format: {self.format}",
            f"  Arch:   {self.arch}",
            f"  Dispatch table: {self.dispatch_count} entries at 0x{self.dispatch_vaddr:x}",
            f"  st_* entries:   {len(self._st_entries)}",
            f"  Symbols:        {len(self._symbols)}",
            f"  Push fns:       {self._push_fns}",
            f"  Stack ptr:      0x{self._stack_ptr_vaddr:x}",
            f"  Error addr:     0x{self._err_addr_vaddr:x}",
            "",
            "── Protocol analysis ──",
        ]
        # Check a few known symbols
        for name in ["_bist_nobs", "_bist_nvar", "_bist_data", "_bist_global"]:
            vaddr = self._symbols.get(name)
            lines.append(f"  {name:30s} → 0x{vaddr:x}" if vaddr else f"  {name} → NOT FOUND")
        return "\n".join(lines)

    def save_cache(self, output_path: Optional[str] = None) -> str:
        """Save the manifest to a JSON file. Returns path written."""
        manifest = self._to_manifest()
        if not output_path:
            cache_dir = Path(".") / "manifests"
            cache_dir.mkdir(exist_ok=True)
            output_path = str(cache_dir / f"manifest-{self.sha256[:16]}.json")
        with open(output_path, "w") as f:
            json.dump(manifest, f, indent=2)
        return output_path

    @classmethod
    def from_cache(cls, path: str, cache_dir: Optional[str] = None,
                   min_version: int = 0) -> Optional["StataBinary"]:
        """Load from cache if available and not stale.

        Parameters
        ----------
        path : str
            Path to the Stata shared library.
        cache_dir : str or None
            Directory containing cached manifests.  Default: ``./manifests/``.
        min_version : int
            Minimum manifest version accepted.  Manifests with a lower
            version are treated as stale and ignored (default ``0`` = any).

        Returns
        -------
        StataBinary or None
            Populated instance if a valid, non-stale cache exists.
        """
        obj = cls(path)
        if cache_dir is None:
            cache_dir = os.path.join(os.path.dirname(__file__), "manifests")
        prefix = f"manifest-{obj.sha256[:16]}.json"
        cache_path = os.path.join(cache_dir, prefix)
        if not os.path.exists(cache_path):
            return None
        with open(cache_path) as f:
            mdata = json.load(f)
        if mdata.get("manifest_version", 0) < min_version:
            return None  # stale
        # Populate from cache
        obj._dispatch_vaddr = mdata.get("dispatch_vaddr", 0)
        obj._dispatch_count = mdata.get("dispatch_count", 0)
        obj._symbols = mdata.get("symbols", {})
        do = mdata.get("data_offsets", {}) or {}
        obj._stack_ptr_vaddr = do.get("stack_ptr_delta", 0) or obj._stack_ptr_vaddr
        obj._err_addr_vaddr = do.get("err_addr_delta", 0) or obj._err_addr_vaddr
        obj._push_fns = mdata.get("push_fns", {}) or obj._push_fns
        obj._st_entries = []  # not cached; re-discover if needed
        obj._analyzed = True
        return obj

    def cache_health(self, cache_dir: Optional[str] = None) -> list[dict]:
        """Report health of all cached manifests.

        Scans *cache_dir* for ``manifest-*.json`` files and returns a
        list of dicts with ``filename``, ``manifest_version``, and
        ``sha256`` for each.
        """
        if not self._analyzed and self._elf is None:
            # Not yet analyzed — just return a basic check
            return [{"sha256": self.sha256, "analyzed": False}]
        if cache_dir is None:
            cache_dir = os.path.join(os.path.dirname(__file__), "manifests")
        results = []
        if not os.path.isdir(cache_dir):
            return results
        for fname in sorted(os.listdir(cache_dir)):
            if not fname.startswith("manifest-") or not fname.endswith(".json"):
                continue
            path = os.path.join(cache_dir, fname)
            try:
                with open(path) as f:
                    mdata = json.load(f)
                results.append({
                    "filename": fname,
                    "manifest_version": mdata.get("manifest_version", 0),
                    "sha256": mdata.get("sha256", "")[:16],
                })
            except (json.JSONDecodeError, OSError):
                results.append({"filename": fname, "error": True})
        return results

    # ═══════════════════════════════════════════════════════════════
    # Discovery
    # ═══════════════════════════════════════════════════════════════

    def _analyze_elf_x86_64(self) -> None:
        """Run all x86_64-specific discovery passes."""
        if not self._elf:
            return
        self._discover_dispatch_table()
        self._discover_st_names()
        self._discover_push_functions()
        self._discover_stack_ptr()
        self._discover_dynamic_symbols()

    def _discover_dispatch_table(self) -> None:
        """Discover dispatch table from .rela.dyn R_X86_64_RELATIVE entries.

        Looks for the largest contiguous run of function-pointer entries
        in .data.rel.ro — this is the dispatch table (1686 entries on SE).
        """
        if not self._elf:
            return
        dr = self._elf.sections.get(".rela.dyn")
        if not dr:
            return
        data = self._elf.raw
        rela_raw = data[dr["offset"]:dr["offset"] + dr["size"]]
        n_rela = dr["size"] // 24
        R_X86_64_RELATIVE = 8

        dr_start = self._elf.sections.get(".data.rel.ro", {}).get("addr", 0)
        dr_end = dr_start + self._elf.sections.get(".data.rel.ro", {}).get("size", 0)
        text_start = self._elf.section_addr(".text")
        text_end = text_start + self._elf.sections.get(".text", {}).get("size", 0)

        entries = []
        for i in range(n_rela):
            entry = rela_raw[i * 24:(i + 1) * 24]
            if len(entry) < 24:
                break
            r_offset, r_info, r_addend = struct.unpack("<QQQ", entry)
            r_type = r_info & 0xFFFFFFFF
            if r_type != R_X86_64_RELATIVE:
                continue
            if not (dr_start <= r_offset < dr_end):
                continue
            if not (text_start <= r_addend < text_end):
                continue
            entries.append((r_offset, r_addend))

        if not entries:
            return

        entries.sort(key=lambda x: x[0])

        # Group consecutive entries spaced exactly 8 bytes apart
        tables = []
        i = 0
        while i < len(entries):
            j = i + 1
            while j < len(entries):
                expected = entries[i][0] + (j - i) * 8
                if entries[j][0] != expected:
                    break
                j += 1
            count = j - i
            if count >= 50:
                tables.append({
                    "vaddr": entries[i][0],
                    "size": count,
                    "entries": [entries[k][1] for k in range(i, j)],
                })
            i = j

        if not tables:
            return

        largest = max(tables, key=lambda t: t["size"])
        self._dispatch_vaddr = largest["vaddr"]
        self._dispatch_entries = largest["entries"]

    def _discover_st_names(self) -> None:
        """Parse .data section for st_* name entries.

        Each entry has: index(4) + flags(4) + reserved(8) + name(null-term).
        Names are mapped to dispatch table indices.
        """
        if not self._elf or not self._dispatch_entries:
            return

        ds = self._elf.sections.get(".data")
        if not ds:
            return
        data_raw = self._elf.raw_of(".data")
        de = self._dispatch_entries

        for off in range(0, len(data_raw) - 20, 1):
            if data_raw[off:off + 16] == b"\0" * 16:
                continue
            try:
                end = data_raw.index(b"\0", off + 16, off + 60)
            except ValueError:
                continue
            name = data_raw[off + 16:end].decode("ascii", errors="replace")
            if not name.startswith("st_"):
                continue
            if any(c > 127 for c in name.encode()):
                continue
            idx, flags, f1, f2 = struct.unpack_from("<IIII", data_raw, off)
            if idx < 10 or idx >= len(de):
                continue
            # Avoid duplicates (prefer first occurrence for each idx)
            existing = [e[1] for e in self._st_entries if e[0] == idx]
            if not existing:
                self._st_entries.append((idx, name, flags))
            elif name not in existing:
                pass  # other names for same idx — skip

        # Build symbols from st_ names → dispatch addresses
        for idx, name, flags in self._st_entries:
            impl_idx = idx + 1 if (flags & 0x100) else idx
            if impl_idx < len(de):
                vmaddr = de[impl_idx]
                self._symbols[f"_bist_{name[3:]}"] = vmaddr
                self._symbols[name] = vmaddr

    def _discover_push_functions(self) -> None:
        """Find _pushdbl, _pushint, _pushstr in .text dynamically.

        Uses structural matching:
        1. Find function prologue (sub rsp, N)
        2. Verify the function body has expected instructions
           (allocator call for _pushdbl, cvtsi2sd for _pushint,
            type=-3 for _pushstr)

        Falls back to empirically verified addresses if discovery fails.
        """
        if not self._elf:
            return

        text_raw = self._elf.text_raw
        text_vaddr = self._elf.text_vaddr

        def _find_in_text(pat: bytes, start: int = 0) -> int:
            return text_raw.find(pat, start, len(text_raw))

        # --- _pushdbl: prologue + movsd xmm0,[rdi] + test rax,rax ---
        # Pattern: sub rsp, 8; movsd xmm0, [rdi]; call XX; test rax, rax
        dbl_pat = bytes([0x48, 0x83, 0xEC, 0x08, 0xF2, 0x0F, 0x10, 0x07])
        idx = _find_in_text(dbl_pat)
        if idx >= 0:
            # Verify: call (E8 XX XX XX XX) followed by test rax,rax (48 85 C0)
            call_start = idx + 8
            if call_start + 7 <= len(text_raw):
                call_insn = text_raw[call_start]
                after_call = text_raw[call_start + 5:call_start + 8]
                if call_insn == 0xE8 and after_call == bytes([0x48, 0x85, 0xC0]):
                    self._push_fns["_pushdbl"] = text_vaddr + idx

        # --- _pushint: sub rsp + cvtsi2sd xmm0,edi ---
        pushint_pat = bytes([0xF2, 0x0F, 0x2A, 0xC7])  # cvtsi2sd xmm0,edi
        search_start = 0
        while '_pushint' not in self._push_fns:
            idx = _find_in_text(pushint_pat, search_start)
            if idx < 0:
                break
            # Verify preceded by sub rsp within 16 bytes
            for back in range(idx - 16, idx):
                if text_raw[back:back+3] == bytes([0x48, 0x83, 0xec]):
                    fn_addr = text_vaddr + back
                    # Verify followed by movsd [rsp+8], xmm0; lea rdi, [rsp+8]
                    # bytes: F2 0F 11 44 24 08 48 8D 7C 24 08
                    store_pat = bytes([0xF2, 0x0F, 0x11, 0x44, 0x24, 0x08,
                                       0x48, 0x8D, 0x7C, 0x24, 0x08])
                    if text_raw[idx+4:idx+15] == store_pat:
                        self._push_fns["_pushint"] = fn_addr
                        break
            search_start = idx + 1

        # --- _pushstr: mov edi, -3 + repne scasb ---
        pushstr_pat = bytes([0xBF, 0xFD, 0xFF, 0xFF, 0xFF])  # mov edi, -3
        scasb_pat = bytes([0xF2, 0xAE])  # repne scasb
        search_start = 0
        while '_pushstr' not in self._push_fns:
            idx = _find_in_text(pushstr_pat, search_start)
            if idx < 0:
                break
            scasb_idx = _find_in_text(scasb_pat, idx)
            if 0 < scasb_idx - idx < 128:
                # Verify function prologue nearby
                for back in range(idx - 64, idx):
                    if text_raw[back:back+3] == bytes([0x48, 0x83, 0xec]):
                        fn_addr = text_vaddr + back
                        # Verify first instruction loads arg into rbp
                        # (mov rbp, rdi = 48 89 FD)
                        if text_raw[back+3:back+6] == bytes([0x48, 0x89, 0xFD]):
                            self._push_fns["_pushstr"] = fn_addr
                            break
            search_start = idx + 1

        # --- Fallback: empirically verified addresses ---
        # These were confirmed via disassembly for Stata 19.5 x86_64.
        if not self._push_fns.get("_pushdbl"):
            self._push_fns["_pushdbl"] = 0x8b23ec
        if not self._push_fns.get("_pushint"):
            self._push_fns["_pushint"] = 0x8b2441
        if not self._push_fns.get("_pushstr"):
            self._push_fns["_pushstr"] = 0x8b2524

        # Add to _symbols so they appear in the manifest
        for pname, paddr in self._push_fns.items():
            if pname not in self._symbols:
                self._symbols[pname] = paddr

    def _discover_stack_ptr(self) -> None:
        """Find stack pointer and error address by scanning .text for the
        ``lea rsi, [rip + off]; mov (rsi), rdx; ...`` pattern."""
        if not self._elf:
            return
        sp_pattern = bytes([
            0x48, 0x8d, 0x35,  # lea rsi, [rip + off]
            0x48, 0x8b, 0x16,  # mov (rsi), rdx
            0x48, 0x8d, 0x4a, 0x08,  # lea rcx, [rdx+8]
            0x48, 0x89, 0x0e,  # mov (rsi), rcx
        ])

        text_raw = self._elf.text_raw
        text_vaddr = self._elf.text_vaddr

        idx = text_raw.find(sp_pattern)
        if idx >= 0:
            # Extract displacement from lea rsi, [rip + disp]
            disp = struct.unpack_from("<i", text_raw, idx + 3)[0]
            lea_addr = text_vaddr + idx
            target = lea_addr + 7 + disp  # 7 = instruction length
            self._stack_ptr_vaddr = target

        # Error address: search for mov dword ptr [rip+...], N pattern
        # inside the same function
        if self._stack_ptr_vaddr:
            err_idx = text_raw.find(bytes([0xc7, 0x05]),
                                    idx - 200, idx + 200)
            if err_idx >= 0:
                disp = struct.unpack_from("<i", text_raw, err_idx + 2)[0]
                target = text_vaddr + err_idx + 10 + disp
                self._err_addr_vaddr = target

        # Fallback: known addresses
        if not self._stack_ptr_vaddr:
            self._stack_ptr_vaddr = ARG_PTR_ADDR
            self._err_addr_vaddr = 0x500C698

    def _discover_dynamic_symbols(self) -> None:
        """Read ELF .dynsym section for exported dynamic symbols.

        Adds symbols like StataSO_Main, StataSO_Execute, etc. to
        self._symbols.  These are required by the runtime engine
        for base address computation.
        """
        if not self._elf:
            return
        ds = self._elf.sections.get(".dynsym")
        dn = self._elf.sections.get(".dynstr")
        if not ds or not dn or ds.get("size", 0) == 0:
            return
        raw = self._elf.raw
        dynsym_data = raw[ds["offset"]:ds["offset"] + ds["size"]]
        dynstr_data = raw[dn["offset"]:dn["offset"] + dn["size"]]
        n_syms = ds["size"] // 24
        for i in range(n_syms):
            entry = dynsym_data[i * 24:(i + 1) * 24]
            if len(entry) < 24:
                break
            st_name, st_info, st_other, st_shndx, st_value, st_size = \
                struct.unpack("<IBBHQQ", entry)
            if st_value == 0:
                continue
            bind = st_info >> 4
            type_ = st_info & 0xF
            # Only add global/weak defined functions and objects
            if bind not in (1, 2):  # STB_GLOBAL, STB_WEAK
                continue
            if type_ not in (2, 1):  # STT_FUNC, STT_OBJECT
                continue
            # Read symbol name from .dynstr
            try:
                end = dynstr_data.index(b"\x00", st_name)
                name = dynstr_data[st_name:end].decode("ascii", errors="replace")
            except (ValueError, UnicodeDecodeError):
                continue
            if not name:
                continue
            # Only add symbols we care about (StataSO_*, _push*, _bist*)
            if any(kw in name for kw in
                   ("StataSO", "_push", "_bist_", "_bi_st_")):
                if name not in self._symbols:
                    self._symbols[name] = st_value

    # ═══════════════════════════════════════════════════════════════
    # Disassembly & Thunk following
    # ═══════════════════════════════════════════════════════════════

    def disassemble(self, vaddr: int, size: int = 128) -> str:
        """Disassemble *size* bytes starting at *vaddr* (absolute ELF vaddr).

        Returns a multi-line string of instructions.
        """
        if not HAS_CAPSTONE or not self._elf:
            return "(capstone not available)"
        off = vaddr - self._elf.text_vaddr
        if off < 0 or off >= len(self._elf.text_raw):
            return f"(address 0x{vaddr:x} out of range)"
        code = self._elf.text_raw[off:min(off + size, len(self._elf.text_raw))]
        md = _Cs(CS_ARCH_X86, CS_MODE_64)
        lines = []
        for i in md.disasm(code, vaddr):
            lines.append(f"  0x{i.address:x}: {i.mnemonic} {i.op_str}")
        return "\n".join(lines)

    def _follow_thunk(self, vaddr: int, max_depth: int = 2) -> list:
        """Disassemble a function, following forward conditional jumps.

        Returns list of (level, address, mnemonic, op_str).
        """
        if not HAS_CAPSTONE or not self._elf:
            return []
        raw = self._elf.text_raw
        text_vaddr = self._elf.text_vaddr
        md = _Cs(CS_ARCH_X86, CS_MODE_64)
        seen = set()
        result: list = []

        def _dis(target_vaddr: int, level: int = 0) -> None:
            if target_vaddr in seen or level > max_depth:
                return
            if target_vaddr < text_vaddr or target_vaddr >= text_vaddr + len(raw):
                return
            seen.add(target_vaddr)
            off = target_vaddr - text_vaddr
            chunk = raw[off:min(off + 200, len(raw))]
            try:
                insns = list(md.disasm(chunk, target_vaddr))
            except Exception:
                return

            branch_targets = set()
            for insn in insns:
                result.append((level, insn.address, insn.mnemonic, insn.op_str))
                # Check for forward conditional jumps
                if insn.mnemonic in ("je", "jne", "jg", "jge", "jl", "jle",
                                     "ja", "jae", "jb", "jbe", "jmp",
                                     "jz", "jnz", "js", "jns"):
                    if "0x" in insn.op_str:
                        try:
                            t = int(insn.op_str.split("0x")[1], 16)
                            if t > insn.address:
                                branch_targets.add(t)
                        except ValueError:
                            pass
                # Check for unconditional call to nearby function
                if insn.mnemonic == "call":
                    if "0x" in insn.op_str:
                        try:
                            t = int(insn.op_str.split("0x")[1], 16)
                            if text_vaddr <= t < text_vaddr + len(raw):
                                branch_targets.add(t)
                        except ValueError:
                            pass

            for target in sorted(branch_targets):
                _dis(target, level + 1)

        _dis(vaddr, 0)
        return result

    # ═══════════════════════════════════════════════════════════════
    # Protocol analysis
    # ═══════════════════════════════════════════════════════════════

    def analyze_dispatch_fn(self, name: str) -> dict:
        """Analyze a specific _bist_ function: follow thunks, detect
        pool-header checks, error codes, and push-str calls."""
        if not name.startswith("_bist_"):
            name = f"_bist_{name}"
        vaddr = self._symbols.get(name)
        if not vaddr:
            return {"name": name, "error": "symbol not found"}

        full_insns = self._follow_thunk(vaddr, max_depth=3)
        disp_idx = None
        for i, dv in enumerate(self._dispatch_entries):
            if dv == vaddr:
                disp_idx = i
                break

        has_pool = False
        calls_push = False
        error_code = None
        for _, addr, mnem, op in full_insns:
            if "- 0x94" in op:
                has_pool = True
            if mnem == "call" and "0x" in op:
                try:
                    t = int(op.split("0x")[1], 16)
                    for _, pv in self._push_fns.items():
                        if abs(t - pv) < 50:
                            calls_push = True
                            break
                except ValueError:
                    pass
            if "mov dword ptr" in f"{mnem} {op}" and "0x" in op:
                parts = op.split(",")
                if len(parts) > 1:
                    try:
                        ec = int(parts[-1].strip(), 16)
                        if 0x100 < ec < 0x10000:
                            error_code = ec
                    except ValueError:
                        pass

        sections = []
        current_label = "thunk"
        current = []
        for level, addr, mnem, op_str in full_insns:
            label = "thunk" if level == 0 else f"impl_level_{level}"
            if label != current_label and current:
                sections.append((current_label, list(current)))
                current = []
                current_label = label
            current.append(f"{'. ' * level}0x{addr:x}: {mnem} {op_str}")
        if current:
            sections.append((current_label, current))

        return {
            "name": name,
            "vaddr": vaddr,
            "size": len(full_insns),
            "dispatch_index": disp_idx,
            "sections": sections,
            "has_pool_header_check": has_pool,
            "calls_push_function": calls_push,
            "error_code": error_code,
        }

    def trace_entry_points(self, name: str) -> list[dict]:
        """Find alternative entry points within a dispatch function body.

        Scans for multi-push prologues and frame allocations (sub rsp)
        that indicate alternative entry points (e.g., _bist_data has
        a read entry at +0 and a write entry at +72).
        """
        if not name.startswith("_bist_"):
            name = f"_bist_{name}"

        # Apply engine-level override for _bist_store → _bist_data
        effective = name
        if name == "_bist_store":
            effective = "_bist_data"
        vaddr = self._symbols.get(effective)
        if not vaddr:
            vaddr = self._symbols.get(name)
        if not vaddr:
            return []

        if not HAS_CAPSTONE or not self._elf:
            return [{"vaddr": vaddr, "offset": 0, "type": "primary"}]

        text_raw = self._elf.text_raw
        text_vaddr = self._elf.text_vaddr
        md = _Cs(CS_ARCH_X86, CS_MODE_64)

        off = vaddr - text_vaddr
        if off < 0 or off >= len(text_raw):
            return []

        chunk = text_raw[off:min(off + 256, len(text_raw))]
        entries = [{"vaddr": vaddr, "offset": 0, "type": "primary"}]
        push_seq_start = None
        push_count = 0

        try:
            insns = list(md.disasm(chunk, vaddr))
        except Exception:
            return entries

        for insn in insns:
            offs = insn.address - vaddr
            if offs == 0:
                continue
            if insn.mnemonic == "push":
                if push_count == 0:
                    push_seq_start = insn.address
                push_count += 1
            else:
                if push_count >= 2 and push_seq_start:
                    entries.append({
                        "vaddr": push_seq_start, "offset": push_seq_start - vaddr,
                        "type": "push_prologue", "push_count": push_count,
                    })
                push_count = 0
                push_seq_start = None
                if insn.mnemonic == "sub" and "rsp" in insn.op_str and offs >= 4:
                    entries.append({
                        "vaddr": insn.address, "offset": offs, "type": "frame_entry",
                    })
        return entries

    def trace_error_codes(self, vaddr: int, max_size: int = 2048) -> list[dict]:
        """Extract error codes from a function body.

        Finds ``mov dword ptr [...], error_code`` instructions and
        captures up to 3 preceding instructions as guard context.
        """
        if not HAS_CAPSTONE or not self._elf:
            return []
        text_raw = self._elf.text_raw
        text_vaddr = self._elf.text_vaddr
        md = _Cs(CS_ARCH_X86, CS_MODE_64)

        off = vaddr - text_vaddr
        if off < 0 or off >= len(text_raw):
            return []
        chunk = text_raw[off:min(off + max_size, len(text_raw))]
        try:
            insns = list(md.disasm(chunk, vaddr))
        except Exception:
            return []

        results = []
        guard = []
        for insn in insns:
            op = f"{insn.mnemonic} {insn.op_str}"
            if insn.mnemonic == "mov" and "dword ptr" in op:
                parts = op.split(",")
                if len(parts) == 2:
                    vs = parts[-1].strip()
                    try:
                        val = int(vs, 16)
                        if 0x100 <= val <= 0xFFFF:
                            results.append({
                                "vaddr": insn.address,
                                "error_code": val,
                                "instruction": op,
                                "guard_context": list(guard[-3:]),
                            })
                    except ValueError:
                        pass
            guard.append(op)
            if len(guard) > 6:
                guard.pop(0)
        return results

    def analyze_protocol(self, name: str) -> dict:
        """Classify a dispatch function's protocol.

        Returns dict with ``protocol_type``: ``"standard_push_stack"``,
        ``"sp_reset"``, ``"no_stack_args"``, or ``"unknown"``.
        """
        if not name.startswith("_bist_"):
            name = f"_bist_{name}"
        vaddr = self._symbols.get(name)
        if not vaddr:
            return {"name": name, "error": "symbol not found"}

        result = {"name": name, "vaddr": vaddr, "protocol_type": "unknown"}
        if not HAS_CAPSTONE or not self._elf:
            return result

        text_raw = self._elf.text_raw
        text_vaddr = self._elf.text_vaddr
        off = vaddr - text_vaddr
        if off < 0 or off >= len(text_raw):
            return result

        md = _Cs(CS_ARCH_X86, CS_MODE_64)
        chunk = text_raw[off:min(off + 50, len(text_raw))]
        try:
            insns = list(md.disasm(chunk, vaddr))
        except Exception:
            return result

        # Look for the SP-reset triple pattern within first 15 instructions
        lea_targets = []
        for insn in insns[:15]:
            if insn.mnemonic == "lea" and "rip" in insn.op_str:
                m = re.search(r"\[rip\s*([+-])\s*(0x[0-9a-fA-F]+)\]", insn.op_str)
                if m:
                    sign = 1 if m.group(1) == "+" else -1
                    disp = int(m.group(2), 16) * sign
                    lea_targets.append({
                        "addr": insn.address, "disp": disp,
                        "target": insn.address + insn.size + disp,
                    })
        # Check for SP-reset pattern
        if len(lea_targets) >= 2:
            second = lea_targets[1]
            # Check if there's a mov [rax], rX after the second lea
            for insn in insns[2:5]:
                if insn.mnemonic == "mov" and "qword ptr" in insn.op_str:
                    if f"[rax]" in insn.op_str or f"[{lea_targets[1].get('reg', 'rsi')}]" in insn.op_str:
                        result["protocol_type"] = "sp_reset"
                        result["arg_buffer_addr"] = second["target"]
                        if lea_targets:
                            result["sp_global_addr"] = lea_targets[0]["target"]
                        return result

        # Check if function reads from ARG_PTR
        for insn in insns[:20]:
            m = re.search(r"\[rip\s*([+-])\s*(0x[0-9a-fA-F]+)\]", insn.op_str)
            if m:
                sign = 1 if m.group(1) == "+" else -1
                disp = int(m.group(2), 16) * sign
                target = insn.address + insn.size + disp
                if target == ARG_PTR_ADDR:
                    result["protocol_type"] = "standard_push_stack"
                    return result

        result["protocol_type"] = "no_stack_args"
        return result

    def analyze_full_protocol(self, name: str) -> dict:
        """Comprehensive protocol analysis combining entry points, error
        codes, ARG_PTR reads, SP_global accesses, and push-str calls."""
        if not name.startswith("_bist_"):
            name = f"_bist_{name}"

        effective = name
        if name == "_bist_store":
            effective = "_bist_data"

        vaddr = self._symbols.get(effective)
        if not vaddr:
            vaddr = self._symbols.get(name)
        if not vaddr:
            return {"name": name, "error": "symbol not found"}

        result = {
            "name": name,
            "effective_name": effective if effective != name else None,
            "vaddr": vaddr,
            "dispatch_index": None,
        }

        for i, dv in enumerate(self._dispatch_entries):
            if dv == vaddr:
                result["dispatch_index"] = i
                break

        if not HAS_CAPSTONE or not self._elf:
            return result

        text_raw = self._elf.text_raw
        text_vaddr = self._elf.text_vaddr
        md = _Cs(CS_ARCH_X86, CS_MODE_64)
        off = vaddr - text_vaddr
        if off < 0 or off >= len(text_raw):
            return result

        # Scan with 2KB backward offset for thunks that call backward
        scan_start = max(0, off - 2048)
        chunk = text_raw[scan_start:min(scan_start + 8192, len(text_raw))]
        scan_base = vaddr - (off - scan_start)

        arg_ptr_reads = []
        sp_global_access = []
        pushstr_calls = []
        edi_checks = []
        entry_candidates = []

        try:
            insns = list(md.disasm(chunk, scan_base))
        except Exception:
            return result

        push_count = 0
        push_seq_start = None

        for insn in insns:
            addr = insn.address
            op = f"{insn.mnemonic} {insn.op_str}"
            offs = addr - vaddr

            # RIP-relative target resolution
            if "rip" in insn.op_str:
                m = re.search(r"\[rip\s*([+-])\s*(0x[0-9a-fA-F]+)\]", insn.op_str)
                if m:
                    sign = 1 if m.group(1) == "+" else -1
                    disp = int(m.group(2), 16) * sign
                    target = addr + insn.size + disp
                    if target == ARG_PTR_ADDR:
                        arg_ptr_reads.append({"vaddr": addr, "offset": offs, "op": op})
                    elif target == SP_GLOBAL_ADDR:
                        sp_global_access.append({
                            "vaddr": addr, "offset": offs, "op": op,
                            "is_write": "mov" in insn.mnemonic and "qword ptr [" in op,
                        })

            # Push string call detection
            if insn.mnemonic == "call" and "0x" in insn.op_str:
                ps_addr = self._push_fns.get("_pushstr", 0)
                if ps_addr:
                    try:
                        t = int(insn.op_str.split("0x")[1], 16)
                        if abs(t - ps_addr) < 5:
                            pushstr_calls.append({"vaddr": addr, "offset": offs})
                    except ValueError:
                        pass

            # EDI arg count checks
            if insn.mnemonic == "cmp" and "edi" in insn.op_str:
                for tok in insn.op_str.split(","):
                    tok = tok.strip()
                    try:
                        val = int(tok, 0)
                        if 0 <= val <= 10:
                            edi_checks.append({"vaddr": addr, "checks": val, "op": op})
                    except ValueError:
                        pass

            # Entry point detection
            if insn.mnemonic == "push":
                if push_count == 0:
                    push_seq_start = addr
                push_count += 1
            else:
                if push_count >= 2 and push_seq_start and push_seq_start != vaddr:
                    entry_candidates.append({
                        "vaddr": push_seq_start, "offset": push_seq_start - vaddr,
                        "type": "push_prologue", "push_count": push_count,
                    })
                push_count = 0
                push_seq_start = None
                if insn.mnemonic == "sub" and "rsp" in insn.op_str and offs >= 4:
                    entry_candidates.append({
                        "vaddr": addr, "offset": offs, "type": "frame_entry",
                    })

        result["arg_ptr_reads"] = arg_ptr_reads
        result["sp_global_access"] = sp_global_access
        result["pushstr_calls"] = pushstr_calls
        result["edi_checks"] = edi_checks
        result["entry_candidates"] = entry_candidates

        uses_stack = len(arg_ptr_reads) > 0
        has_multi = len(entry_candidates) > 0
        has_edi = len(edi_checks) > 0
        calls_ps = len(pushstr_calls) > 0

        # Detect tsmat[0x36] arg-type protocol and numeric-arg stub
        has_tsmat36_check = False
        has_numeric_stub = False
        numeric_stub_error = None
        for insn in insns[:40]:
            op = f"{insn.mnemonic} {insn.op_str}"
            # Check for movzx edx, byte ptr [rax + 0x36] pattern
            if insn.mnemonic == "movzx" and "0x36" in insn.op_str:
                has_tsmat36_check = True
            # Check for numeric-arg stub: error 0xC20 set then immediate ret
            if insn.mnemonic == "mov" and "0xc20" in insn.op_str.lower():
                has_numeric_stub = True
                numeric_stub_error = 0xC20
            # Check for error 0xC1E (arg type != 0)
            if insn.mnemonic == "mov" and "0xc1e" in insn.op_str.lower():
                numeric_stub_error = 0xC1E

        if has_tsmat36_check:
            result["tsmat36_protocol"] = True
            if has_numeric_stub:
                result["numeric_arg_stub"] = True
                result["numeric_stub_error"] = hex(numeric_stub_error) if numeric_stub_error else "0xc20"
                result["note"] = ("String-arg protocol: tsmat[0x36] != 0 required. "
                                  "Numeric args (tsmat[0x36]==0) hit error stub. "
                                  "Use _push_str not _push_double._push_int.")
            else:
                result["note"] = "String-arg protocol: tsmat[0x36] != 0 required"
        elif not uses_stack:
            result["protocol_type"] = "no_stack_args"
            result["note"] = "No ARG_PTR read — uses internal global"
        elif has_edi and has_multi:
            result["protocol_type"] = "read_write"
            for ec in edi_checks:
                v = ec["checks"]
                if v == 2: result["read_arg_count"] = 2
                elif v == 3: result["write_arg_count"] = 3
                elif v == 4: result["write_arg_count"] = 4
            result.setdefault("read_arg_count", 2)
            result["note"] = "Combined read/write (multi-entry)"
        elif has_edi:
            result["protocol_type"] = "branching"
        elif calls_ps:
            result["protocol_type"] = "string_return"
        else:
            result["protocol_type"] = "push_stack_call"

        result["uses_push_stack"] = uses_stack
        result["error_codes"] = self.trace_error_codes(vaddr, max_size=4096)

        # Run full push-call trace (all types) to augment protocol detection
        all_push_calls = self.trace_all_push_calls(vaddr, max_size=4096)
        if all_push_calls:
            result["push_calls"] = all_push_calls
            push_types = {p.get("push_function", "") for p in all_push_calls}
            if "_pushstr" in push_types and result["protocol_type"] == "push_stack_call":
                result["protocol_type"] = "string_return"

        # Run pool-header check detection
        pool_checks = self.trace_pool_checks(vaddr, max_size=4096)
        if pool_checks:
            result["pool_checks"] = pool_checks

        return result

    def trace_calling_convention(self, name: str) -> dict:
        """Determine the exact calling convention for a dispatch function.

        Analyzes entry points, edi checks, push call types, and register
        flow to infer:
        - Number and types of arguments
        - Return type (double, string, void, int)
        - Which entry point handles which argument count
        - Whether the function uses SP-resetting or push+stack protocol

        Returns
        -------
        dict with keys:
            - ``name``: function name
            - ``vaddr``: virtual address
            - ``inferred_args``: list of (type, description) tuples
            - ``return_type``: "double", "string", "int", or "void"
            - ``protocol``: "push+stack", "sp_reset", or "internal_global"
            - ``entry_points``: each entry with arg_count and description
            - ``confidence``: 0.0–1.0
        """
        if not name.startswith("_bist_"):
            name = f"_bist_{name}"

        effective = name
        if name == "_bist_store":
            effective = "_bist_data"

        vaddr = self._symbols.get(effective)
        if not vaddr:
            vaddr = self._symbols.get(name)
        if not vaddr:
            return {"name": name, "error": "symbol not found"}

        result = {
            "name": name,
            "vaddr": vaddr,
            "inferred_args": [],
            "return_type": "unknown",
            "protocol": "unknown",
            "entry_points": [],
            "confidence": 0.0,
        }

        if not HAS_CAPSTONE or not self._elf:
            return result

        text_raw = self._elf.text_raw
        text_vaddr = self._elf.text_vaddr
        md = _Cs(CS_ARCH_X86, CS_MODE_64)
        off = vaddr - text_vaddr
        if off < 0 or off >= len(text_raw):
            return result

        # Scan a wider range (8KB) to catch push calls and edi checks
        scan_start = max(0, off - 4096)
        chunk = text_raw[scan_start:min(scan_start + 12288, len(text_raw))]
        scan_base = vaddr - (off - scan_start)

        try:
            insns = list(md.disasm(chunk, scan_base))
        except Exception:
            return result

        # Collect evidence
        edi_checks: list[dict] = []
        push_call_targets: list[tuple[int, str]] = []  # (vaddr, push_type)
        has_sp_reset = False
        has_arg_ptr = False
        entry_sequences: list[dict] = []

        push_count = 0
        push_seq_start = None

        push_map: dict[int, str] = {}
        for pname, paddr in self._push_fns.items():
            push_map[paddr] = pname

        for insn in insns:
            addr = insn.address
            op = f"{insn.mnemonic} {insn.op_str}"

            # RIP-relative ARG_PTR read / SP_global write
            if "rip" in insn.op_str:
                m = re.search(r"\[rip\s*([+-])\s*(0x[0-9a-fA-F]+)\]", insn.op_str)
                if m:
                    sign = 1 if m.group(1) == "+" else -1
                    disp = int(m.group(2), 16) * sign
                    target = addr + insn.size + disp
                    if target == ARG_PTR_ADDR:
                        has_arg_ptr = True
                    elif target == SP_GLOBAL_ADDR and "mov" in insn.mnemonic:
                        has_sp_reset = True

            # Push function call detection (all types)
            if insn.mnemonic == "call" and "0x" in insn.op_str:
                try:
                    target = int(insn.op_str.split("0x")[1], 16)
                    for paddr, pname in push_map.items():
                        if abs(target - paddr) < 20:
                            push_call_targets.append((addr, pname))
                            break
                except ValueError:
                    pass

            # EDI arg count checks
            if insn.mnemonic == "cmp" and "edi" in insn.op_str:
                for tok in insn.op_str.split(","):
                    tok = tok.strip()
                    try:
                        val = int(tok, 0)
                        if 0 <= val <= 10:
                            edi_checks.append({"vaddr": addr, "checks": val, "op": op})
                    except ValueError:
                        pass

            # Push prologue detection (entry points)
            if insn.mnemonic == "push":
                if push_count == 0:
                    push_seq_start = addr
                push_count += 1
            else:
                if push_count >= 2 and push_seq_start and push_seq_start != vaddr:
                    entry_sequences.append({
                        "vaddr": push_seq_start,
                        "push_count": push_count,
                        "type": "push_prologue",
                    })
                push_count = 0
                push_seq_start = None

        # Infer protocol type
        if has_sp_reset and not has_arg_ptr and not push_call_targets:
            result["protocol"] = "sp_reset"
            result["return_type"] = "int"
            result["inferred_args"] = []
            result["entry_points"] = entry_sequences
            result["confidence"] = 0.9
        elif has_arg_ptr or push_call_targets:
            result["protocol"] = "push+stack"
            # Infer args from push call pattern
            push_type_names = [t for _, t in push_call_targets]
            str_count = sum(1 for t in push_type_names if "_pushstr" in t)
            dbl_count = sum(1 for t in push_type_names if "_pushdbl" in t or "_pushint" in t)
            if str_count > 0:
                result["inferred_args"] = [
                    ("string", "scalar name or macro name (first arg is string)"),
                ]
                result["return_type"] = "string"
            elif dbl_count > 0:
                result["inferred_args"] = [
                    ("double", "numeric value or index"),
                ]
                result["return_type"] = "double"

            # Edi checks tell us the arg count variants
            if edi_checks:
                for ec in edi_checks:
                    result["entry_points"].append({
                        "vaddr": ec["vaddr"],
                        "arg_count": ec["checks"],
                        "description": f"edi=={ec['checks']} at 0x{ec['vaddr']:x}",
                    })
            result["confidence"] = 0.7
        else:
            result["protocol"] = "internal_global"
            result["confidence"] = 0.3

        return result

    def validate_protocol(self, name: str) -> dict:
        """Validate the push+stack protocol setup for a dispatch function.

        Checks:
        - Pool-header magic (``data_ptr[-0x94] == 0x2b``)
        - ARG_PTR self-pointer (``[-0x10] == tsmat_ptr``)
        - String return flag (``tsmat[0x34] == 0xFFFD`` for string returns)
        - SP_global reset pattern

        Returns
        -------
        dict with:
        - ``valid``: bool (all checks pass)
        - ``checks``: list of check results
        - ``pool_header_ok``: bool
        - ``self_ptr_ok``: bool
        - ``string_flag_ok``: bool or None
        - ``sp_reset_ok``: bool
        """
        if not name.startswith("_bist_"):
            name = f"_bist_{name}"
        vaddr = self._symbols.get(name)
        if not vaddr:
            return {"valid": False, "error": "symbol not found"}

        if not HAS_CAPSTONE or not self._elf:
            return {"valid": False, "error": "capstone not available"}

        text_raw = self._elf.text_raw
        text_vaddr = self._elf.text_vaddr
        md = _Cs(CS_ARCH_X86, CS_MODE_64)
        off = vaddr - text_vaddr
        if off < 0 or off >= len(text_raw):
            return {"valid": False, "error": "not in .text"}

        chunk = text_raw[off:min(off + 4096, len(text_raw))]
        try:
            insns = list(md.disasm(chunk, vaddr))
        except Exception:
            return {"valid": False, "error": "disassembly failed"}

        checks: list[dict] = []
        pool_header_ok = False
        self_ptr_ok = False
        string_flag_ok: Optional[bool] = None
        sp_reset_ok = False

        for insn in insns:
            addr = insn.address
            op = f"{insn.mnemonic} {insn.op_str}"

            # Pool-header check: cmp dword ptr [rax-0x94], 0x2b
            if insn.mnemonic == "cmp" and "-0x94" in insn.op_str and "0x2b" in insn.op_str:
                pool_header_ok = True
                checks.append({"vaddr": addr, "type": "pool_header", "pass": True,
                              "detail": "pool-header check for 0x2b magic found"})

            # Self-pointer patch: mov [rax-0x10], rax or similar
            if insn.mnemonic == "mov" and "-0x10" in insn.op_str:
                self_ptr_ok = True
                checks.append({"vaddr": addr, "type": "self_ptr", "pass": True,
                              "detail": "tsmat self-pointer at [-0x10]"})

            # String return flag: cmp [rax+0x34], -3 (0xFFFD)
            if insn.mnemonic == "cmp" and "+0x34" in insn.op_str and "-3" in insn.op_str.split(",")[1:]:
                string_flag_ok = True
                checks.append({"vaddr": addr, "type": "string_flag", "pass": True,
                              "detail": "string return flag tsmat[0x34] == 0xFFFD"})

            # SP_global reset: mov [global], rdx or similar
            if "rip" in insn.op_str:
                m = re.search(r"\[rip\s*([+-])\s*(0x[0-9a-fA-F]+)\]", insn.op_str)
                if m:
                    sign = 1 if m.group(1) == "+" else -1
                    disp = int(m.group(2), 16) * sign
                    target = addr + insn.size + disp
                    if target == SP_GLOBAL_ADDR and "mov" in insn.mnemonic:
                        sp_reset_ok = True
                        checks.append({"vaddr": addr, "type": "sp_reset", "pass": True,
                                      "detail": "SP_global address loaded"})

        return {
            "valid": pool_header_ok and sp_reset_ok,
            "checks": checks,
            "pool_header_ok": pool_header_ok,
            "self_ptr_ok": self_ptr_ok,
            "string_flag_ok": string_flag_ok,
            "sp_reset_ok": sp_reset_ok,
        }

    def register_flow_trace(self, vaddr: int, max_size: int = 4096) -> dict:
        """Trace register values through a function to understand data flow.

        Follows assignments to key registers (rax, rbx, rcx, rdx, rsi,
        rdi, r8, r9, r10, r11, r12, r13, r14, r15) and tracks:
        - Constant assignments (mov eax, 0)
        - Memory reads that load from computed addresses
        - Calls whose results flow into registers
        - Conditional branches based on register values

        Returns
        -------
        dict with:
        - ``entry_vaddr``: starting address
        - ``register_states``: list of (vaddr, reg, value/description)
        - ``interesting_flows``: descriptions of important data flows
        """
        if not HAS_CAPSTONE or not self._elf:
            return {"entry_vaddr": vaddr, "register_states": [], "interesting_flows": []}

        text_raw = self._elf.text_raw
        text_vaddr = self._elf.text_vaddr
        md = _Cs(CS_ARCH_X86, CS_MODE_64)
        off = vaddr - text_vaddr
        if off < 0 or off >= len(text_raw):
            return {"entry_vaddr": vaddr, "register_states": [], "interesting_flows": []}

        chunk = text_raw[off:min(off + max_size, len(text_raw))]
        try:
            insns = list(md.disasm(chunk, vaddr))
        except Exception:
            return {"entry_vaddr": vaddr, "register_states": [], "interesting_flows": []}

        register_states: list[dict] = []
        interesting_flows: list[str] = []

        # Track register assignments
        regs = {
            "rax": None, "rbx": None, "rcx": None, "rdx": None,
            "rsi": None, "rdi": None,
            "r8": None, "r9": None, "r10": None, "r11": None,
            "r12": None, "r13": None, "r14": None, "r15": None,
            "eax": None, "ebx": None, "ecx": None, "edx": None,
            "esi": None, "edi": None,
        }

        for insn in insns:
            mnem = insn.mnemonic
            op = insn.op_str
            addr = insn.address

            # Track constant assignments: mov reg, const
            if mnem in ("mov", "movzx", "movsxd") and "," in op:
                parts = op.split(",", 1)
                dst = parts[0].strip()
                src = parts[1].strip()
                if dst in regs:
                    try:
                        val = int(src, 0)
                        regs[dst] = val
                        if val <= 0xFFFF:  # Skip large addresses
                            register_states.append({
                                "vaddr": addr, "reg": dst, "value": val
                            })
                    except ValueError:
                        if "qword ptr" in src or "dword ptr" in src:
                            regs[dst] = "*" + src
                            register_states.append({
                                "vaddr": addr, "reg": dst, "value": f"load({src})"
                            })
                        else:
                            regs[dst] = f"{mnem}({src})"

            # Track comparisons that matter for argument flow
            if mnem == "cmp" and "edi" in op:
                for tok in op.split(","):
                    tok = tok.strip()
                    try:
                        val = int(tok, 0)
                        interesting_flows.append(
                            f"0x{addr:x}: arg count check — edi == {val}")
                    except ValueError:
                        pass

            # Track test/compare with error codes
            if mnem == "cmp" and "0x" in op:
                for tok in op.split(","):
                    tok = tok.strip()
                    try:
                        val = int(tok, 0)
                        if 0xC00 <= val <= 0xD00:  # Stata error code range
                            interesting_flows.append(
                                f"0x{addr:x}: error code check — 0x{val:x}")
                    except ValueError:
                        pass

        return {
            "entry_vaddr": vaddr,
            "register_states": register_states,
            "interesting_flows": interesting_flows,
        }

    def trace_jump_table(self, vaddr: int, table_rip_offset: int,
                         entry_count: int = 8) -> list[dict]:
        """Resolve a jump table referenced via ``lea rdx, [rip + offset]``.

        Returns list of {index, target_addr} for each entry in the table.
        """
        if not HAS_CAPSTONE or not self._elf:
            return []
        text_raw = self._elf.text_raw
        text_vaddr = self._elf.text_vaddr
        # The jump table is at text_vaddr + the RIP-relative offset
        table_vaddr = vaddr + table_rip_offset
        table_file_off = table_vaddr - text_vaddr
        if table_file_off < 0 or table_file_off + entry_count * 4 > len(text_raw):
            return []
        import struct
        results = []
        table_data = text_raw[table_file_off:table_file_off + entry_count * 4]
        for i in range(entry_count):
            disp = struct.unpack_from("<i", table_data, i * 4)[0]
            target = table_vaddr + disp
            results.append({"index": i, "disp": disp, "target_vaddr": target})
        return results

    def auto_test_call_convention(self, name: str) -> dict:
        """Analyze a dispatch function to determine its calling convention.

        Uses static disassembly to analyze:
        - Entry points (thunk → implementation)
        - Arg count checks (edi comparisons)
        - Push function calls (pushstr/pushdbl/pushint)
        - Error codes set
        - Expression parser calls

        Returns a dict with:
        - ``entry_points``: detected entry points
        - ``edi_checks``: arg count branches
        - ``push_functions_called``: which push functions are called
        - ``error_codes``: error codes that would be set
        - ``behavior_type``: whether it's a lookup, stub, or identity fn
        - ``inferred_args``: guessed arg types based on push calls

        NOTE: For live dispatch testing with a running Stata engine,
        use ``ProtocolAutoTester.diagnose_failure()`` instead.
        """
        result: dict = {
            "name": name,
            "entry_points": [],
            "edi_checks": [],
            "push_functions_called": [],
            "error_codes": [],
            "behavior_type": "unknown",
            "calls_expression_parser": False,
        }

        if not HAS_CAPSTONE or not self._elf:
            return result

        text_raw = self._elf.text_raw
        text_vaddr = self._elf.text_vaddr
        md = _Cs(CS_ARCH_X86, CS_MODE_64)

        vaddr = self._symbols.get(name)
        if not vaddr:
            result["error"] = f"{name} not found"
            return result

        # Get entry points
        entries_raw = self._follow_thunk(vaddr, max_depth=2)
        entry_addrs = [vaddr]
        if entries_raw:
            for ep in entries_raw:
                if isinstance(ep, tuple) and len(ep) >= 2 and isinstance(ep[1], int):
                    entry_addrs.append(ep[1])
        seen = set()
        entry_addrs = [x for x in entry_addrs if not (x in seen or seen.add(x))]

        result["entry_points"] = entry_addrs

        # Disassemble each entry point looking for patterns
        has_push_call = False
        has_parser_call = False
        error_codes_seen: list[int] = []
        push_targets: list[str] = []

        for ep_addr in entry_addrs[:3]:
            off = ep_addr - text_vaddr
            if off < 0 or off >= len(text_raw):
                continue
            chunk = text_raw[off:min(off + 4096, len(text_raw))]
            try:
                insns = list(md.disasm(chunk, ep_addr))
            except Exception:
                continue

            for insn in insns:
                op = f"{insn.mnemonic} {insn.op_str}"
                a = insn.address

                # EDI checks
                if insn.mnemonic == "cmp" and "edi" in op:
                    for tok in insn.op_str.split(","):
                        tok = tok.strip()
                        try:
                            result["edi_checks"].append(int(tok, 0))
                        except ValueError:
                            pass

                # Push function calls
                if insn.mnemonic == "call":
                    for tok in insn.op_str.split():
                        tok = tok.strip()
                        try:
                            target = int(tok, 16)
                            # Check against known push function addrs
                            if self._push_fns:
                                for pname, paddr in self._push_fns.items():
                                    if abs(target - paddr) < 10:
                                        has_push_call = True
                                        push_targets.append(pname)
                                        result["push_functions_called"].append(pname)
                                        break
                            # Expression parser
                            if abs(target - 0x81c988) < 10:
                                has_parser_call = True
                                result["calls_expression_parser"] = True
                            if abs(target - 0x81d2b9) < 10:
                                result["calls_string_converter"] = True
                        except ValueError:
                            pass

                # Error codes
                if insn.mnemonic == "mov" and "0x" in op:
                    for tok in op.split(","):
                        tok = tok.strip()
                        try:
                            val = int(tok, 0)
                            if 0xC00 <= val <= 0xD00:
                                error_codes_seen.append(val)
                        except ValueError:
                            pass

        result["error_codes"] = list(dict.fromkeys(error_codes_seen))
        result["edi_checks"] = list(dict.fromkeys(result["edi_checks"]))

        # Determine behavior type
        if has_push_call and has_parser_call:
            result["behavior_type"] = "expression_evaluator"
            result["inferred_args"] = "string_arg"
        elif has_push_call:
            result["behavior_type"] = "push_result"
            result["inferred_args"] = "depends_on_edi"
        elif error_codes_seen:
            result["behavior_type"] = "error_stub"
        else:
            result["behavior_type"] = "unknown"

        # Check if identity function (reads arg, pushes same value back)
        if has_push_call and has_parser_call:
            result["likely_identity"] = True
            result["identity_reason"] = (
                "Calls expression parser then pushes result — likely echoes input"
            )

        return result

    def live_test_protocol(self, name: str,
                           call_fn: Optional[callable] = None
                           ) -> dict:
        """Verify inferred protocol by calling the function live.

        Parameters
        ----------
        name : str
            Dispatch function name (e.g. ``"_bist_nobs"``).
        call_fn : callable or None
            A ``callable(name, *args)`` that invokes the dispatch function
            via a running Stata engine and returns ``(rc, result)``.
            If *None*, the method returns the protocol inference only.

        Returns
        -------
        dict
            ``{"inferred": ..., "live": ...}`` with the static protocol
            inference and, if *call_fn* was provided, the live test result.

        Example
        -------
        >>> from pystata_x.sfi._engine import StataEngine
        >>> eng = StataEngine()
        >>> b.live_test_protocol("_bist_nobs", call_fn=eng.call)
        {"inferred": {"protocol_type": "no_stack_args", ...},
         "live": {"rc": 0, "result": 74}}

        Architecture note
        -----------------
        Dispatch functions follow one of three protocol patterns:

        **Standard push+stack** (``_bist_data``, ``_bist_global``, etc.)
          Arguments are pushed via ``_push_double`` / ``_push_int`` /
          ``_push_str`` which allocate tsmat structs on the engine's
          internal stack and update ARG_PTR (``0x500C6A0``).  The
          dispatch implementation reads from these tsmat structs by
          indexing backward from ARG_PTR.  This is the PRIMARY protocol
          for all data-access functions.

        **SP-resetting** (``_bist_nobs``, ``_bist_nvar``, etc.)
          The dispatch thunk writes a descriptor address into SP_global
          (``0x500C638``) and the implementation reads data from a
          global C struct, not from push+stack.  No push function calls
          are needed.  These are always 0-arg or 1-arg functions that
          return a simple scalar.

        **Internal-global** (``_bist_store`` write path)
          The implementation reads from a global struct that the thunk
          sets up from Stata internals, not from ARG_PTR.  These are
          typically write-side functions where the caller is expected
          to have gone through a type-checking dispatch thunk first.
        """
        proto = self.analyze_full_protocol(name)
        result = {"inferred": proto, "live": None}
        if call_fn is not None:
            try:
                rc, live_result = call_fn(name)
                result["live"] = {"rc": rc, "result": live_result}
            except Exception as e:
                result["live"] = {"error": str(e)}
        return result

    # ═══════════════════════════════════════════════════════════════
    #  Enhanced analysis methods for rich doc generation
    # ═══════════════════════════════════════════════════════════════

    def trace_all_push_calls(self, vaddr: int, max_size: int = 4096
                             ) -> list[dict]:
        """Find all calls to push functions (_pushdbl/_pushint/_pushstr)
        within a function body.  Returns list with vaddr, target, and
        inferred push type."""
        if not HAS_CAPSTONE or not self._elf:
            return []
        text_raw = self._elf.text_raw
        text_vaddr = self._elf.text_vaddr
        md = _Cs(CS_ARCH_X86, CS_MODE_64)
        off = vaddr - text_vaddr
        if off < 0 or off >= len(text_raw):
            return []
        chunk = text_raw[off:min(off + max_size, len(text_raw))]
        try:
            insns = list(md.disasm(chunk, vaddr))
        except Exception:
            return []

        # Build address to name map for push functions
        push_map: dict[int, str] = {}
        for pname, paddr in self._push_fns.items():
            push_map[paddr] = pname

        results = []
        for insn in insns:
            if insn.mnemonic == "call" and "0x" in insn.op_str:
                try:
                    target = int(insn.op_str.split("0x")[1], 16)
                    for paddr, pname in push_map.items():
                        if abs(target - paddr) < 20:
                            results.append({
                                "vaddr": insn.address,
                                "target_vaddr": target,
                                "push_function": pname,
                                "offset": insn.address - vaddr,
                            })
                            break
                except ValueError:
                    pass
        return results

    def disassemble_basic_blocks(self, vaddr: int, max_size: int = 2048
                                 ) -> list[dict]:
        """Disassemble and organize into basic blocks.

        Each block has: start_vaddr, instructions (list of dicts),
        branch_target, fallthrough, and outgoing edges.
        """
        if not HAS_CAPSTONE or not self._elf:
            return []
        text_raw = self._elf.text_raw
        text_vaddr = self._elf.text_vaddr
        md = _Cs(CS_ARCH_X86, CS_MODE_64)
        off = vaddr - text_vaddr
        if off < 0 or off >= len(text_raw):
            return []
        chunk = text_raw[off:min(off + max_size, len(text_raw))]
        try:
            insns = list(md.disasm(chunk, vaddr))
        except Exception:
            return []

        if not insns:
            return []

        TERMINAL = {"jmp", "ret", "call", "int3", "hlt"}
        COND_JUMPS = {"je", "jne", "jg", "jge", "jl", "jle",
                      "ja", "jae", "jb", "jbe",
                      "jz", "jnz", "js", "jns", "jnp", "jp",
                      "jo", "jno", "jrcxz", "loop", "loope",
                      "loopne"}

        blocks: list[dict] = []
        current_block: dict = {
            "start_vaddr": insns[0].address,
            "instructions": [],
            "branch_target": None,
            "fallthrough": None,
        }
        for insn in insns:
            cur = {
                "vaddr": insn.address,
                "mnemonic": insn.mnemonic,
                "op_str": insn.op_str,
                "bytes": insn.bytes.hex(),
            }
            # Check if this instruction is a branch target (gap since prev)
            if current_block["instructions"]:
                prev_addr = current_block["instructions"][-1]["vaddr"]
                if insn.address > prev_addr + 15:
                    # Gap — start new block
                    blocks.append(current_block)
                    current_block = {
                        "start_vaddr": insn.address,
                        "instructions": [],
                        "branch_target": None,
                        "fallthrough": None,
                    }

            current_block["instructions"].append(cur)
            current_block["end_vaddr"] = insn.address

            if insn.mnemonic in COND_JUMPS:
                # Extract target
                try:
                    for part in insn.op_str.split(","):
                        if "0x" in part:
                            t = int(part.split("0x")[1], 16)
                            current_block["branch_target"] = t
                            next_addr = insn.address + insn.size
                            current_block["fallthrough"] = next_addr
                            break
                except ValueError:
                    pass
                blocks.append(current_block)
                current_block = {
                    "start_vaddr": insn.address + insn.size,
                    "instructions": [],
                    "branch_target": None,
                    "fallthrough": None,
                }
            elif insn.mnemonic in TERMINAL:
                if insn.mnemonic == "jmp":
                    try:
                        if "0x" in insn.op_str:
                            t = int(insn.op_str.split("0x")[1], 16)
                            current_block["branch_target"] = t
                    except ValueError:
                        pass
                blocks.append(current_block)
                current_block = {
                    "start_vaddr": insn.address + insn.size,
                    "instructions": [],
                    "branch_target": None,
                    "fallthrough": None,
                }

        # Flush last block if non-empty
        if current_block["instructions"]:
            blocks.append(current_block)

        return blocks

    def trace_pool_checks(self, vaddr: int, max_size: int = 4096) -> list[dict]:
        """Find pool-header check sites (tsmat[-0x94] comparisons)
        within a function body."""
        if not HAS_CAPSTONE or not self._elf:
            return []
        text_raw = self._elf.text_raw
        text_vaddr = self._elf.text_vaddr
        md = _Cs(CS_ARCH_X86, CS_MODE_64)
        off = vaddr - text_vaddr
        if off < 0 or off >= len(text_raw):
            return []
        chunk = text_raw[off:min(off + max_size, len(text_raw))]
        try:
            insns = list(md.disasm(chunk, vaddr))
        except Exception:
            return []

        results = []
        for insn in insns:
            op = f"{insn.mnemonic} {insn.op_str}"
            if "- 0x94" in op or "- 148" in op:
                results.append({
                    "vaddr": insn.address,
                    "instruction": op,
                    "offset": insn.address - vaddr,
                })
        return results

    def get_function_size(self, vaddr: int, max_scan: int = 4096) -> int:
        """Estimate function size by scanning for 'ret' instruction."""
        if not HAS_CAPSTONE or not self._elf:
            return 0
        text_raw = self._elf.text_raw
        text_vaddr = self._elf.text_vaddr
        md = _Cs(CS_ARCH_X86, CS_MODE_64)
        off = vaddr - text_vaddr
        if off < 0 or off >= len(text_raw):
            return 0
        chunk = text_raw[off:min(off + max_scan, len(text_raw))]
        try:
            insns = list(md.disasm(chunk, vaddr))
        except Exception:
            return 0
        for insn in insns:
            if insn.mnemonic == "ret":
                return (insn.address + insn.size) - vaddr
        return min(max_scan, len(chunk))

    # ═══════════════════════════════════════════════════════════════
    # Manifest
    # ═══════════════════════════════════════════════════════════════

    def _to_manifest(self) -> dict:
        """Build a manifest dict from discovered data."""
        return self.generate_manifest()

    # ═══════════════════════════════════════════════════════════════
    #  Extended manifest (version 3)
    # ═══════════════════════════════════════════════════════════════

    def generate_manifest(self) -> dict:
        """Generate a compact per-platform manifest (version 3).

        Extends the existing _to_manifest() format with:
        - memory_offsets (var tables, hash tables discovered via analysis)
        - dispatch_function_status (working/echo/unknown per function)
        - platform + arch fields for cross-platform diff support
        - manifest_version = 3
        """
        # Check each dispatch function for echo behavior
        dispatch_status = {}
        if HAS_CAPSTONE:
            for name in sorted(self._symbols):
                if name.startswith("_bist_") and name != "_bist_store":
                    status = self._classify_dispatch_fn(name)
                    if status:
                        dispatch_status[name] = status

        base = {
            "manifest_version": 3,
            "sha256": self.sha256,
            "platform": sys.platform,
            "arch": self.arch,
            "n_bist_symbols": len(self._symbols),
            "symbols": dict(self._symbols),
            "dispatch_entries": list(self._dispatch_entries),
            "dispatch_vaddr": self._dispatch_vaddr,
            "st_entries": [(idx, name, hex(flags))
                           for idx, name, flags in self._st_entries],
            "push_fns": dict(self._push_fns),
            "data_offsets": {
                "stack_ptr_delta": self._stack_ptr_vaddr,
                "err_addr_delta": self._err_addr_vaddr,
            },
            "memory_offsets": self.analyze_memory_layout(),
            "dispatch_function_status": dispatch_status,
        }
        return base

    def _classify_dispatch_fn(self, name: str) -> dict | None:
        """Classify a dispatch function as 'working', 'echo', or 'unknown'.

        Uses combined static analysis:
        - Checks for expression parser calls (strong echo signal)
        - Checks for meaningful memory reads to .data/.bss
        - Delegates to ``auto_test_call_convention()`` for deeper analysis
        """
        if not HAS_CAPSTONE or not self._elf:
            return None
        vaddr = self._symbols.get(name)
        if not vaddr:
            return None
        text_raw = self._elf.text_raw
        text_vaddr = self._elf.text_vaddr
        off = vaddr - text_vaddr
        if off < 0 or off >= len(text_raw):
            return None

        md = _Cs(CS_ARCH_X86, CS_MODE_64)
        scan_start = max(0, off - 2048)
        chunk = text_raw[scan_start:min(scan_start + 8192, len(text_raw))]
        scan_base = vaddr - (off - scan_start)

        try:
            insns = list(md.disasm(chunk, scan_base))
        except Exception:
            return None

        has_mem_read = False
        has_ret = False
        instr_count = 0
        calls_expression_parser = False
        calls_push_function = False
        has_real_table_lookup = False

        for insn in insns:
            addr = insn.address
            if addr < vaddr:
                continue
            if addr > vaddr + 512:
                break
            instr_count += 1
            if insn.mnemonic == "ret":
                has_ret = True

            # Check for calls to expression parser (0x81c988) — strong echo signal
            if insn.mnemonic == "call" and "0x" in insn.op_str:
                for tok in insn.op_str.split():
                    tok = tok.strip()
                    try:
                        target = int(tok, 16)
                        # Expression parser — identity function calls this to
                        # evaluate the input and push it back
                        if abs(target - 0x81c988) < 10:
                            calls_expression_parser = True
                        # Push functions
                        for pname, paddr in self._push_fns.items():
                            if abs(target - paddr) < 10:
                                calls_push_function = True
                                break
                    except ValueError:
                        pass

            # RIP-relative memory reads
            if "rip" in insn.op_str and insn.mnemonic in ("mov", "lea", "add", "cmp"):
                m = re.search(r"\[rip\s*([+-])\s*(0x[0-9a-fA-F]+)\]", insn.op_str)
                if m:
                    sign = 1 if m.group(1) == "+" else -1
                    disp = int(m.group(2), 16) * sign
                    target = addr + insn.size + disp
                    # Check if target is in .data or .bss
                    for sname, sdata in (self._elf.sections.items()
                                         if self._elf else {}):
                        saddr = sdata.get("addr", 0)
                        ssize = sdata.get("size", 0)
                        if saddr <= target < saddr + ssize:
                            # Reads from .bss are more meaningful than .text reads
                            if sname in (".bss", ".data", ".data.rel.ro"):
                                has_real_table_lookup = True
                            has_mem_read = True
                            break

        if instr_count == 0:
            return None

        evidence = []

        # Strong echo signals
        if calls_expression_parser:
            evidence.append("calls expression parser")
            # Expression parser + push function = identity stub
            if calls_push_function:
                return {
                    "classification": "echo",
                    "instr_count": instr_count,
                    "has_mem_read": has_mem_read,
                    "calls_expression_parser": True,
                    "note": "Calls expression parser and push functions — "
                            "identity stub that echoes input",
                }
            return {
                "classification": "likely_echo",
                "instr_count": instr_count,
                "has_mem_read": has_mem_read,
                "calls_expression_parser": True,
                "note": "Calls expression parser — likely echoes or "
                        "evaluates expression rather than doing table lookup",
            }

        # Strong working signal: reads from .bss/.data tables
        if has_real_table_lookup and instr_count >= 30:
            return {
                "classification": "working",
                "instr_count": instr_count,
                "has_mem_read": True,
                "has_table_lookup": True,
                "note": f"Reads from data/bss tables, {instr_count} instr — "
                        "likely real implementation",
            }

        # Short function with no real table reads — likely echo
        if instr_count < 20 and not has_real_table_lookup:
            return {
                "classification": "likely_echo",
                "instr_count": instr_count,
                "has_mem_read": has_mem_read,
                "note": f"Short ({instr_count} instr) with no table reads — "
                        "likely identity stub",
            }

        # Fall back to auto_test_call_convention for deeper analysis
        try:
            cc = self.auto_test_call_convention(name)
            behavior = cc.get("behavior_type", "unknown")
            likely_id = cc.get("likely_identity", False)
            if likely_id:
                return {
                    "classification": "echo",
                    "instr_count": instr_count,
                    "has_mem_read": has_mem_read,
                    "behavior_type": behavior,
                    "note": cc.get("identity_reason", "auto_test: likely_identity"),
                }
        except Exception:
            pass

        # Default: working (conservative, as most functions do work)
        return {
            "classification": "working",
            "instr_count": instr_count,
            "has_mem_read": has_mem_read,
            "has_table_lookup": has_real_table_lookup,
            "note": f"{instr_count} instr, mem_read={has_mem_read}, "
                    f"table_lookup={has_real_table_lookup}",
        }

    # ═══════════════════════════════════════════════════════════════
    #  Memory Layout Discovery
    # ═══════════════════════════════════════════════════════════════

    def analyze_memory_layout(self) -> dict:
        """Discover internal memory locations from dispatch function code.

        For each dispatch function, disassembles its code to find
        RIP-relative memory references.  By correlating references
        across related functions, we can identify:
        - Variable name/type/format tables
        - Scalar hash tables
        - Macro hash tables
        - Value label hash tables
        - c() constant locations
        - Other .bss/.data globals

        Returns a dict of discovered memory regions:
        {
            "var_name_table": {"vaddr": 0x..., "stride": 96},
            "var_type_table": {"vaddr": 0x..., "stride": 2},
            "scalar_table": {"vaddr": 0x...},
            "macro_table": {"vaddr": 0x...},
            "valuelabel_table": {"vaddr": 0x...},
            "max_vars_addr": 0x...,
        }
        """
        if not HAS_CAPSTONE or not self._elf:
            return {}

        # Track all RIP-relative targets found, grouped by function
        fn_mem_refs: dict[str, list[int]] = {}

        for name in sorted(self._symbols):
            if not name.startswith("_bist_") or name == "_bist_store":
                continue
            vaddr = self._symbols.get(name)
            if not vaddr:
                continue

            text_raw = self._elf.text_raw
            text_vaddr = self._elf.text_vaddr
            off = vaddr - text_vaddr
            if off < 0 or off >= len(text_raw):
                continue

            md = _Cs(CS_ARCH_X86, CS_MODE_64)
            scan_start = max(0, off - 2048)
            chunk = text_raw[scan_start:min(scan_start + 8192, len(text_raw))]
            scan_base = vaddr - (off - scan_start)

            try:
                insns = list(md.disasm(chunk, scan_base))
            except Exception:
                continue

            refs = []
            for insn in insns:
                if insn.address < vaddr or insn.address > vaddr + 256:
                    continue
                if "rip" in insn.op_str:
                    m = re.search(r"\[rip\s*([+-])\s*(0x[0-9a-fA-F]+)\]",
                                  insn.op_str)
                    if m:
                        sign = 1 if m.group(1) == "+" else -1
                        disp = int(m.group(2), 16) * sign
                        target = insn.address + insn.size + disp
                        refs.append(target)

            if refs:
                fn_mem_refs[name] = refs

        # Correlate references across functions to identify known tables
        from collections import Counter

        # Filter out infrastructure addresses from all reference pools
        def _filter_infra(refs: list[int]) -> list[int]:
            return [r for r in refs if r not in _INFRASTRUCTURE_ADDRS]

        # Identify known tables by correlating function names with
        # their non-infrastructure RIP-relative references.
        #
        # Strategy: For each function, we collect the non-infrastructure
        # addresses it references via RIP-relative addressing.  We then
        # look for addresses that are uniquely referenced by a specific
        # function type (e.g., only `_bist_varlabel` references the
        # variable metadata table).
        #
        # KEY INSIGHT: On x86_64, some dispatch functions 'echo' — they
        # call the expression evaluator instead of doing direct table
        # lookups.  These echo functions only reference infrastructure
        # (ARG_PTR, SP_global).  Working functions reference additional
        # .bss/.data globals that are the actual data tables.
        #
        # We use a naming heuristic: the presence of a specific substring
        # in the function name tells us which table it's likely accessing.
        # But within the candidate refs we look for addresses that are
        # shared by functions with the same naming intent but NOT shared
        # by functions with OTHER naming intents.
        memory_offsets: dict = {}

        # Build a map of all non-infra refs per function
        clean_refs = {n: _filter_infra(refs)
                      for n, refs in fn_mem_refs.items()}

        # Define function groups by naming intent
        groups = {
            'var_metadata': [  # shared name + type + format table
                n for n in clean_refs
                if any(kw in n for kw in
                       ('varname', 'varlabel', 'vartype', 'varformat',
                        'varvaluelabel', 'varindex', 'isstrvar', 'isnumvar',
                        'isalias', 'isnumfmt', 'sortlist'))
            ],
            'scalar': [
                n for n in clean_refs
                if 'numscalar' in n or 'strscalar' in n
            ],
            'macro': [
                n for n in clean_refs
                if 'macroexpand' in n or ('global' in n and '_hcat' not in n)
            ],
            'valuelabel': [
                n for n in clean_refs
                if n.startswith('_bist_vl')
            ],
        }

        # For each region we want to discover, look at the relevant group
        # and find addresses unique to that group.
        region_map = {
            'var_name_table': ('var_metadata', 'varlabel'),
            'var_type_table': ('var_metadata', 'vartype'),
            'scalar_table': ('scalar', ''),
            'macro_table': ('macro', ''),
            'valuelabel_table': ('valuelabel', ''),
        }

        for region_name, (group_name, fn_substr) in region_map.items():
            fns = groups.get(group_name, [])
            if not fns:
                continue

            # Collect refs from functions in this group
            group_refs: Counter = Counter()
            for fn in fns:
                group_refs.update(clean_refs.get(fn, []))

            # Collect refs from ALL functions OUTSIDE this group
            outside_fns = [n for n in clean_refs if n not in fns]
            outside_refs: Counter = Counter()
            for fn in outside_fns:
                outside_refs.update(clean_refs.get(fn, []))

            # If a fn_substr is specified, also find refs unique to
            # functions with that substring within the group
            if fn_substr:
                subset_fns = [n for n in fns if fn_substr in n]
                other_group_fns = [n for n in fns if fn_substr not in n]
            else:
                subset_fns = fns
                other_group_fns = []

            # Build candidate list: refs that appear in this group but
            # rarely or never outside it
            candidates = []
            for addr, group_count in group_refs.most_common(20):
                outside_count = outside_refs.get(addr, 0)

                # If we have a subset (e.g., only 'varlabel' in
                # 'var_metadata'), check that the ref is also
                # group-exclusive relative to OTHERS IN THE SAME GROUP
                in_other_group = 0
                for fn in other_group_fns:
                    if addr in clean_refs.get(fn, []):
                        in_other_group += 1

                # Prefer refs that are NOT shared with other group members
                exclusivity_bonus = 0 if in_other_group == 0 else -in_other_group

                candidates.append((addr, group_count, outside_count,
                                   exclusivity_bonus))

            if not candidates:
                continue

            # Sort: most references in group, least outside, most exclusive
            candidates.sort(key=lambda x: (-x[1], x[2], -x[3]))
            best_addr, best_count, best_outside, _ = candidates[0]

            # Compute confidence
            total_in_group = sum(1 for fn in fns if clean_refs.get(fn))
            confidence = min(1.0, max(best_count - best_outside, 0) /
                            max(total_in_group, 1))

            memory_offsets[region_name] = {
                'vaddr': best_addr,
                'confidence': round(confidence, 2),
            }

        # Add known strides for tables
        if 'var_name_table' in memory_offsets:
            memory_offsets['var_name_table']['stride'] = 96
        if 'var_type_table' in memory_offsets:
            memory_offsets['var_type_table']['stride'] = 2

        # ── Empirical override section ────────────────────────────────
        #
        # Some offsets are empirically verified against the running Stata
        # engine and are known to be correct for this binary.  We
        # override auto-discovered values when we have high confidence
        # from empirical testing.
        #
        # On x86_64 Linux (ELF), Stata stores the variable name table
        # pointer at _BASE + 0x4C9BA08 and the variable type table
        # pointer at _BASE + 0x4C9BA00.  These are .bss globals that
        # hold pointers to heap-allocated tables.
        #
        # The framework-discovered values may differ because echo
        # functions don't access these tables, diluting the correlation.
        # We use the empirically verified values when available.
        EMPIRICAL_OVERRIDES = {
            'var_name_table': {
                'vaddr': 0x4c9ba08,
                'stride': 129,
                'confidence': 1.0,
                'source': 'empirical (verified: make, price, mpg...)',
            },
            'var_type_table': {
                'vaddr': 0x4c9ba00,
                'stride': 2,
                'confidence': 1.0,
                'source': 'empirical (verified: int, float, str18...)',
            },
        }
        for key, override in EMPIRICAL_OVERRIDES.items():
            # Only apply override if this binary shows the expected
            # pattern (the address is in a valid section)
            vaddr = override['vaddr']
            if self._elf:
                for sname, sdata in self._elf.sections.items():
                    saddr = sdata.get('addr', 0)
                    ssize = sdata.get('size', 0)
                    if saddr <= vaddr < saddr + ssize:
                        if sname in ('.bss', '.data'):
                            memory_offsets[key] = dict(override)
                        break

        return memory_offsets

    def _is_valid_section_addr(self, vaddr: int) -> bool:
        """Check if a vaddr falls in a writable data section (.bss, .data)."""
        if not self._elf:
            return False
        for sname, sdata in self._elf.sections.items():
            saddr = sdata.get('addr', 0)
            ssize = sdata.get('size', 0)
            if saddr <= vaddr < saddr + ssize:
                return sname in ('.bss', '.data', '.data.rel.ro')
        return False

        return memory_offsets


# ═══════════════════════════════════════════════════════════════════
#  Module-level helpers
# ═══════════════════════════════════════════════════════════════════


def diff_manifests(m1_path: str, m2_path: str) -> dict:
    """Compare two manifest JSON files and report differences.

    Useful for detecting platform drift between Linux and Windows
    manifests, or changes across Stata versions.

    Parameters
    ----------
    m1_path : str
        Path to first manifest (e.g. Linux ELF manifest).
    m2_path : str
        Path to second manifest (e.g. Windows PE manifest).

    Returns
    -------
    dict with keys:
        - ``same_symbols``: symbols present in both with their addrs
        - ``linux_only``: symbols only in m1
        - ``windows_only``: symbols only in m2
        - ``offset_diffs``: list of data_offsets/memory_offsets that differ
        - ``aligned_symbols``: count of symbols at same address
        - ``misaligned_symbols``: count of symbols at different addresses
        - ``compatible``: True if structural differences are minor
        - ``summary``: human-readable summary string
    """
    def _load(path: str) -> dict:
        with open(path) as f:
            return json.load(f)

    m1 = _load(m1_path)
    m2 = _load(m2_path)

    syms1 = set(m1.get("symbols", {}))
    syms2 = set(m2.get("symbols", {}))

    both = syms1 & syms2
    only_m1 = syms1 - syms2
    only_m2 = syms2 - syms1

    same_addr = 0
    diff_addr = 0
    addr_diffs = []
    for name in sorted(both):
        a1 = m1["symbols"][name]
        a2 = m2["symbols"][name]
        if a1 == a2:
            same_addr += 1
        else:
            diff_addr += 1
            addr_diffs.append({
                "name": name,
                f"{m1.get('platform', 'm1')}_addr": hex(a1),
                f"{m2.get('platform', 'm2')}_addr": hex(a2),
            })

    # Diff data_offsets
    offset_diffs = []
    do1 = m1.get("data_offsets", {}) or {}
    do2 = m2.get("data_offsets", {}) or {}
    for key in set(list(do1.keys()) + list(do2.keys())):
        v1 = do1.get(key)
        v2 = do2.get(key)
        if v1 != v2:
            offset_diffs.append({
                "field": key,
                "m1": hex(v1) if isinstance(v1, int) else v1,
                "m2": hex(v2) if isinstance(v2, int) else v2,
            })

    # Diff memory_offsets
    mo1 = m1.get("memory_offsets", {}) or {}
    mo2 = m2.get("memory_offsets", {}) or {}
    for region in set(list(mo1.keys()) + list(mo2.keys())):
        r1 = mo1.get(region, {})
        r2 = mo2.get(region, {})
        vaddr1 = r1.get("vaddr") if isinstance(r1, dict) else r1
        vaddr2 = r2.get("vaddr") if isinstance(r2, dict) else r2
        if vaddr1 != vaddr2:
            offset_diffs.append({
                "field": f"memory_offsets.{region}",
                "m1": hex(vaddr1) if isinstance(vaddr1, int) else str(vaddr1),
                "m2": hex(vaddr2) if isinstance(vaddr2, int) else str(vaddr2),
            })

    # Diff dispatch function status
    status_diffs = []
    ds1 = m1.get("dispatch_function_status", {}) or {}
    ds2 = m2.get("dispatch_function_status", {}) or {}
    for name in sorted(set(list(ds1.keys()) + list(ds2.keys()))):
        c1 = ds1.get(name, {}).get("classification", "unknown")
        c2 = ds2.get(name, {}).get("classification", "unknown")
        if c1 != c2:
            status_diffs.append({
                "name": name,
                "m1": c1,
                "m2": c2,
            })

    n_total = len(syms1 | syms2)
    n_both = len(both)
    compatibility_issues = []
    diff_addr_threshold = 0.05  # 5%

    if diff_addr / max(n_both, 1) > diff_addr_threshold:
        compatibility_issues.append(
            f"{diff_addr}/{n_both} shared symbols have different addresses "
            f"({100 * diff_addr / max(n_both, 1):.1f}%)")
    if offset_diffs:
        compatibility_issues.append(
            f"{len(offset_diffs)} offset differences")
    if status_diffs:
        compatibility_issues.append(
            f"{len(status_diffs)} function status differences")

    compatible = len(compatibility_issues) == 0

    summary_parts = [
        f"Manifest diff: {m1.get('platform', '?')} vs {m2.get('platform', '?')}",
        f"  Symbols: {n_both} shared, {len(only_m1)} only in m1, "
        f"{len(only_m2)} only in m2",
        f"  Address alignment: {same_addr} same, {diff_addr} different",
        f"  Offset diffs: {len(offset_diffs)}",
        f"  Status diffs: {len(status_diffs)}",
        f"  Compatible: {compatible}",
    ]
    if not compatible:
        summary_parts.append("  Issues:")
        for issue in compatibility_issues:
            summary_parts.append(f"    - {issue}")

    return {
        "m1_platform": m1.get("platform", "?"),
        "m2_platform": m2.get("platform", "?"),
        "m1_arch": m1.get("arch", "?"),
        "m2_arch": m2.get("arch", "?"),
        "total_symbols_m1": len(syms1),
        "total_symbols_m2": len(syms2),
        "same_symbols": {name: {
            m1.get("platform", "m1"): hex(m1["symbols"][name]),
            m2.get("platform", "m2"): hex(m2["symbols"][name]),
        } for name in sorted(both)},
        "m1_only": sorted(only_m1),
        "m2_only": sorted(only_m2),
        "aligned_symbols": same_addr,
        "misaligned_symbols": diff_addr,
        "addr_diffs": addr_diffs,
        "offset_diffs": offset_diffs,
        "status_diffs": status_diffs,
        "compatible": compatible,
        "compatibility_issues": compatibility_issues,
        "summary": "\n".join(summary_parts),
    }

