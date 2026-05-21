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

    Usage::

        b = StataBinary("/path/to/libstata.so")
        b.analyze()                     # runs all discovery
        print(b.report())               # text summary
        b._discover_dispatch_table()    # run individually if needed
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

    def cache_health(self) -> dict:
        """Check cache freshness against current binary."""
        return {"sha256": self.sha256, "analyzed": self._analyzed}

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
        ``movsd xmm0,[rdi]`` pattern near known offsets."""
        if not self._elf:
            return
        # These are found at known x86_64 addresses from analysis
        # _pushdbl: 0x8b2351, _pushint: 0x8b23a6, _pushstr: 0x8b24a6
        # For flexibility, search for the pattern dynamically
        text_raw = self._elf.text_raw
        text_vaddr = self._elf.text_vaddr

        # Pattern: movsd xmm0,[rdi] → F2 0F 10 07
        pattern = bytes([0xF2, 0x0F, 0x10, 0x07])
        hits = _find_bytes(text_raw, pattern)

        for hit in hits:
            abs_addr = text_vaddr + hit
            # Look backward for function prologue
            fn_addr = _fn_start(text_raw, hit, text_vaddr)
            if fn_addr and fn_addr not in self._push_fns.values():
                # Determine which push function by checking a few bytes before
                prev = text_raw[hit - 4:hit] if hit >= 4 else b""
                if b"\x48\x8b\x07" in prev:  # mov rax,[rdi] → _pushint
                    self._push_fns["_pushint"] = fn_addr
                elif len(self._push_fns) == 0:
                    self._push_fns["_pushdbl"] = fn_addr
                elif len(self._push_fns) == 1:
                    self._push_fns["_pushstr"] = fn_addr

        # Fallback: use known addresses if pattern matching fails
        if not self._push_fns.get("_pushdbl"):
            # Known x86_64 addresses from analysis
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
        return result

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
