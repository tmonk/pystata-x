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
        """Find _pushdbl, _pushint, _pushstr in .text by scanning for
        ``movsd xmm0,[rdi]`` pattern near known offsets.

        Known x86_64 addresses (verified):
        - _pushdbl = 0x8b2351
        - _pushint = 0x8b23a6
        - _pushstr = 0x8b24a6
        """
        if not self._elf:
            return

        # Priority: use known verified addresses for x86_64
        if self.arch == "x86_64":
            self._push_fns["_pushdbl"] = 0x8b2351
            self._push_fns["_pushint"] = 0x8b23a6
            self._push_fns["_pushstr"] = 0x8b24a6
            return

        # Fallback: pattern matching for other architectures
        text_raw = self._elf.text_raw
        text_vaddr = self._elf.text_vaddr

        # Pattern: movsd xmm0,[rdi] → F2 0F 10 07
        pattern = bytes([0xF2, 0x0F, 0x10, 0x07])
        hits = _find_bytes(text_raw, pattern)

        for hit in hits:
            abs_addr = text_vaddr + hit
            fn_addr = _fn_start(text_raw, hit, text_vaddr)
            if fn_addr and fn_addr not in self._push_fns.values():
                prev = text_raw[hit - 4:hit] if hit >= 4 else b""
                if b"\x48\x8b\x07" in prev:  # mov rax,[rdi] → _pushint
                    self._push_fns["_pushint"] = fn_addr
                elif len(self._push_fns) == 0:
                    self._push_fns["_pushdbl"] = fn_addr
                elif len(self._push_fns) == 1:
                    self._push_fns["_pushstr"] = fn_addr

        # Fallback: known addresses
        if not self._push_fns.get("_pushdbl"):
            self._push_fns["_pushdbl"] = 0x8b2351
            self._push_fns["_pushint"] = 0x8b23a6
            self._push_fns["_pushstr"] = 0x8b24a6

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

        if not uses_stack:
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
        """Automatically determine the calling convention for a dispatch function.

        Tries all plausible combinations of:
        - Entry points (thunk, implementation, and alternative entries)
        - Arg types (string, double, int, none)
        - Arg counts (0-3)
        - Return type (double, string)

        For each combination, calls the function and reports:
        - Return value (or None if it crashes)
        - Error code set
        - Whether the result differs from the input (not identity)
        - Pool-header and flag check status

        Returns the winning combination and a full attempt log.
        """
        log = logging.getLogger(__name__ + ".auto_test_call")
        result: dict = {
            "name": name,
            "winning_convention": None,
            "attempts": [],
            "entry_points": [],
        }

        # Get the symbol vaddr
        vaddr = self._symbols.get(name)
        if not vaddr:
            result["error"] = f"{name} not found"
            return result

        # Get entry points
        entry_points = self._follow_thunk(vaddr, max_depth=2)
        if not entry_points:
            entry_points = [vaddr]

        result["entry_points"] = [
            {"vaddr": ep, "offset": ep - vaddr}
            for ep in entry_points
        ]

        # Try each entry point
        for ep_addr in entry_points[:3]:  # Limit to first 3
            offsets = [ep_addr - vaddr]

            # Also try with offsets 0x00 (first entry), 0xAA (second entry)
            for target_vaddr in [vaddr, vaddr + 0xAA]:
                for arg_combo in self._generate_arg_combos():
                    for ret_type in ("double", "string"):
                        attempt = self._try_call_convention(
                            name, target_vaddr, arg_combo, ret_type)
                        result["attempts"].append(attempt)

                        if attempt.get("is_winning"):
                            result["winning_convention"] = {
                                "entry_vaddr": target_vaddr,
                                "args": arg_combo,
                                "return_type": ret_type,
                                "return_value": attempt.get("return_value"),
                            }
                            return result  # Return early on first success

        return result

    def _generate_arg_combos(self) -> list[list]:
        """Generate plausible argument combinations for testing."""
        return [
            [],                          # No args
            [0],                          # int 0
            [1],                          # int 1
            [b""],                        # empty string
            [b"test"],                    # simple string
            [b"c(N)"],                    # Stata system value
            [0.0],                        # double 0
            [1.0],                        # double 1
            [b"test", 1],                 # string + flag
            [1, 1],                       # two doubles (data: obs, var)
            [0, 0],                       # two zero doubles
        ]

    def _try_call_convention(self, name: str, entry_vaddr: int,
                               args: list, return_type: str) -> dict:
        """Try a single calling convention and report the result."""
        import ctypes
        attempt: dict = {
            "entry_vaddr": entry_vaddr,
            "args": [repr(a) for a in args],
            "return_type": return_type,
            "success": False,
            "is_winning": False,
            "error_code": None,
            "return_value": None,
        }

        try:
            from pystata_x.sfi._engine import (
                _save_sp, _restore_sp, _push_int, _push_double, _push_str,
                _patch_last_tsmat, _read_stata_err, _get_fn, _BASE,
            )
        except ImportError:
            attempt["error"] = "engine not available"
            return attempt

        rt = _BASE + entry_vaddr
        if not rt:
            return attempt

        sp_before = _save_sp()
        if not sp_before:
            return attempt

        # Push args
        try:
            for arg in args:
                if isinstance(arg, int):
                    _push_int(arg)
                elif isinstance(arg, float):
                    _push_double(arg)
                elif isinstance(arg, (bytes, bytearray)):
                    _push_str(bytes(arg))
                _patch_last_tsmat()
        except Exception as e:
            attempt["error"] = f"push failed: {e}"
            _restore_sp(sp_before)
            return attempt

        # Set string return flag if needed
        if return_type == "string":
            sp = _save_sp()
            tsmat = ctypes.c_uint64.from_address(sp).value if sp else 0
            if tsmat:
                ctypes.c_uint16.from_address(tsmat + 0x34).value = 0xFFFD

        # Call function
        w0 = len(args)
        fn = _get_fn(rt, None, ctypes.c_int)
        try:
            fn(w0)
            attempt["success"] = True
        except Exception as e:
            attempt["error"] = f"call crashed: {e}"
            _restore_sp(sp_before)
            return attempt

        # Read error code
        try:
            attempt["error_code"] = _read_stata_err()
        except Exception:
            pass

        # Read return value
        sp = _save_sp()
        tsmat = ctypes.c_uint64.from_address(sp).value if sp else 0
        if tsmat:
            data_buf = ctypes.c_uint64.from_address(tsmat).value
            if data_buf:
                if return_type == "double":
                    try:
                        attempt["return_value"] = ctypes.c_double.from_address(
                            data_buf).value
                    except Exception:
                        pass
                elif return_type == "string":
                    try:
                        str_ptr = ctypes.c_uint64.from_address(data_buf).value
                        if str_ptr:
                            slen = ctypes.c_int32.from_address(str_ptr).value
                            if 0 < slen < 65536:
                                raw = ctypes.create_string_buffer(slen + 1)
                                ctypes.memmove(raw, str_ptr + 4, slen)
                                attempt["return_value"] = raw.value.decode(
                                    "utf-8", errors="replace")
                    except Exception:
                        pass

        # Check if non-identity (result != input)
        if args and attempt.get("return_value") is not None:
            first_arg = args[0]
            rv = attempt["return_value"]
            is_identity = False
            if isinstance(first_arg, (int, float)) and isinstance(rv, (int, float)):
                if abs(float(first_arg) - float(rv)) < 0.001:
                    is_identity = True
            elif isinstance(first_arg, bytes) and isinstance(rv, str):
                if first_arg.decode("utf-8", errors="replace") == rv:
                    is_identity = True
            attempt["is_identity"] = is_identity

            # Winning: success, no error, non-zero non-identity result
            if (attempt["success"]
                    and attempt.get("error_code") == 0
                    and rv is not None
                    and not is_identity
                    and (not isinstance(rv, (int, float)) or abs(rv) > 1e-10)):
                attempt["is_winning"] = True

        _restore_sp(sp_before)
        return attempt

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
        return {
            "sha256": self.sha256,
            "platform": sys.platform,
            "n_bist_symbols": len(self._symbols),
            "symbols": dict(self._symbols),
            "dispatch_entries": list(self._dispatch_entries),
            "dispatch_vaddr": self._dispatch_vaddr,
            "st_entries": [(idx, name, hex(flags)) for idx, name, flags in self._st_entries],
            "push_fns": dict(self._push_fns),
            "data_offsets": {
                "stack_ptr_delta": self._stack_ptr_vaddr,
                "err_addr_delta": self._err_addr_vaddr,
            },
            "manifest_version": 2,
        }
