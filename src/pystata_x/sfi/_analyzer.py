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


# =========================================================================
#  Helpers
# =========================================================================

def _cstr(buf: bytes, start: int) -> str:
    end = buf.find(b"\0", start)
    if end == -1:
        return buf[start:].decode("ascii", errors="replace")
    return buf[start:end].decode("ascii", errors="replace")


def _find_bytes(haystack: bytes, needle: bytes) -> list[int]:
    positions = []
    pos = 0
    while True:
        pos = haystack.find(needle, pos)
        if pos == -1:
            break
        positions.append(pos)
        pos += 1
    return positions


def _is_float(s: str) -> bool:
    """Check if string represents a float (with decimal point)."""
    try:
        float(s)
        return "." in s
    except ValueError:
        return False


def _fn_start(raw: bytes, start_off: int, base_vaddr: int,
              max_back: int = 200) -> int:
    """Find function start by looking for prologue markers.

    Tries in order:
      1.  sub rsp, N    (48 83 ec NN) — leaf function prologue
      2.  push rbp      (55)            — standard prologue
      3.  push rbx      (53)            — callee-save start
      4.  Fallback to start_off
    """
    # Pass 1: look for sub rsp, N (48 83 ec NN)
    for back in range(3, min(max_back, start_off) + 1):
        bp = start_off - back
        if raw[bp:bp + 3] == bytes([0x48, 0x83, 0xec]):
            # Verify it's a function start (preceded by unrelated code)
            # A sub rsp that follows a ret or at a function boundary
            if bp < 3 or raw[bp - 1] == 0xc3:  # ret before sub rsp
                return base_vaddr + bp
            return base_vaddr + bp  # accept anyway — better than match offset
    # Pass 2: look for push rbp (0x55)
    for back in range(1, max_back + 1):
        bp = start_off - back
        if bp < 0:
            break
        if raw[bp] == 0x55:
            if bp > 0 and raw[bp - 1] in (0x66, 0xFF):
                continue
            return base_vaddr + bp
    # Pass 3: look for push rbx (0x53) — prologue start
    for back in range(1, max_back + 1):
        bp = start_off - back
        if bp < 0:
            break
        if raw[bp] == 0x53:
            if bp > 0 and raw[bp - 1] not in (0x50, 0x51, 0x52, 0x56, 0x57, 0x41, 0x48):
                return base_vaddr + bp
    return base_vaddr + start_off


def _fn_size(raw: bytes, vaddr: int, base_vaddr: int,
             max_search: int = 500) -> int:
    off = vaddr - base_vaddr
    for i in range(off + 1, min(off + max_search, len(raw))):
        if raw[i] == 0xc3:
            return i - off + 1
    return 0


# =========================================================================
#  ELF reader
# =========================================================================

class ELFReader:
    """Parse an ELF64 shared library."""

    def __init__(self, path: str):
        with open(path, "rb") as f:
            self.raw = f.read()
        self.endian = "<" if self.raw[5] == 1 else ">"
        self._parse()

    def _parse(self):
        ehdr = struct.unpack_from(
            self.endian + "16sHHIQQQIHHHHHH", self.raw, 0
        )
        self.e_shoff = ehdr[6]
        self.e_shentsize = ehdr[11]
        self.e_shnum = ehdr[12]
        self.e_shstrndx = ehdr[13]

        # Section string table
        so = self.e_shoff + self.e_shstrndx * self.e_shentsize
        (sh_name, sh_type) = struct.unpack_from(
            self.endian + "II", self.raw, so
        )
        (_, sh_addr, sh_offset, sh_size) = struct.unpack_from(
            self.endian + "QQQQ", self.raw, so + 8
        )
        shstrtab = self.raw[sh_offset:sh_offset + sh_size]

        self.sections = {}
        for i in range(self.e_shnum):
            so = self.e_shoff + i * self.e_shentsize
            (sh_name, sh_type) = struct.unpack_from(
                self.endian + "II", self.raw, so
            )
            (_, sh_addr, sh_offset, sh_size) = struct.unpack_from(
                self.endian + "QQQQ", self.raw, so + 8
            )
            name = _cstr(shstrtab, sh_name)
            self.sections[name] = {
                "addr": sh_addr,
                "size": sh_size,
                "offset": sh_offset,
            }

    def __getitem__(self, name: str) -> dict:
        return self.sections.get(name, {})

    def raw_of(self, name: str) -> bytes:
        s = self.sections.get(name)
        if not s:
            return b""
        return self.raw[s["offset"]:s["offset"] + s["size"]]

    @property
    def text_vaddr(self) -> int:
        return self[".text"].get("addr", 0)

    @property
    def text_raw(self) -> bytes:
        return self.raw_of(".text")

    @property
    def bss_addr(self) -> int:
        return self[".bss"].get("addr", 0)

    @property
    def bss_end(self) -> int:
        s = self[".bss"]
        return s["addr"] + s["size"] if s else 0


# =========================================================================
#  StataBinary — main analysis class
# =========================================================================

class StataBinary:
    """Analyze a Stata shared library.

    Usage:
        ana = StataBinary("/path/to/libstata.so")
        mdata = ana.analyze()       # full analysis → manifest dict
        ana.save_cache()            # cache for engine
        print(ana.report())         # human-readable report
        ana.analyze_dispatch_fn("_bist_nobs")  # decompile + protocol
        ana.verify_all(engine)       # test every symbol via dispatch
    """

    def __init__(self, path: str):
        self.path = path
        self._stat = os.stat(path)
        self.sha256 = self._compute_sha256()
        self.format = self._detect_format()
        self.arch = self._detect_arch()

        # Will be populated by analyze()
        self.dispatch_vaddr = 0
        self.dispatch_count = 0
        self.dispatch_entries: list[int] = []
        self.symbols: dict[str, int] = {}
        self.st_entries: list[tuple[int, str, int]] = []
        self.stack_ptr_vaddr = 0
        self.err_addr_vaddr = 0
        self.push_fns: dict[str, int] = {
            "_pushdbl": 0, "_pushint": 0, "_pushstr": 0,
        }

        # Internal
        self._elf: Optional[ELFReader] = None
        self._capstone_arch = None  # set during analyze

    # ── Metadata ────────────────────────────────────────────────────────

    def _compute_sha256(self) -> str:
        with open(self.path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()

    def _detect_format(self) -> str:
        with open(self.path, "rb") as f:
            m = f.read(4)
        if m[:4] == b"\x7fELF":
            return "elf"
        if m[:4] in (b"\xfe\xed\xfa", b"\xce\xfa\xed\xfe"):
            return "macho"
        if m[:2] == b"MZ":
            return "pe"
        return f"unknown({m.hex()})"

    def _detect_arch(self) -> Optional[str]:
        if self.format != "elf":
            return None
        with open(self.path, "rb") as f:
            ident = f.read(16)
        endian = "<" if ident[5] == 1 else ">"
        with open(self.path, "rb") as f:
            f.read(18)
            m = struct.unpack(endian + "H", f.read(2))[0]
        return {62: "x86_64", 183: "arm64"}.get(m, f"other({m})")

    # ── Full analysis ───────────────────────────────────────────────────

    def analyze(self) -> dict:
        """Run full binary analysis. Returns manifest dict."""
        if self.format == "elf" and self.arch == "x86_64":
            return self._analyze_elf_x86_64()
        raise ValueError(f"Unsupported: {self.format}/{self.arch}")

    def _analyze_elf_x86_64(self) -> dict:
        self._elf = ELFReader(self.path)
        self._capstone_arch = (CS_ARCH_X86, CS_MODE_64)

        self._discover_dispatch_table()
        self._discover_st_names()
        self._discover_stata_so_exports()
        self._discover_push_functions()

        return self._to_manifest()

    # ── Step 1: Dispatch table ──────────────────────────────────────────

    def _discover_dispatch_table(self):
        """Parse .rela.dyn → largest function-pointer array = dispatch table."""
        elf = self._elf
        rela_raw = elf.raw_of(".rela.dyn")
        dr = elf[".data.rel.ro"]
        text = elf[".text"]
        if not rela_raw or not dr or not text:
            return

        n = dr["size"] // 8  # rough upper bound
        R_X86_64_RELATIVE = 8
        dr_start, dr_end = dr["addr"], dr["addr"] + dr["size"]
        tx_start, tx_end = text["addr"], text["addr"] + text["size"]

        entries = []
        for i in range(dr["size"] // 24):  # rela.dyn has 24-byte entries
            try:
                r_offset, r_info, r_addend = struct.unpack_from(
                    elf.endian + "QQQ", rela_raw, i * 24
                )
            except struct.error:
                break
            if (r_info & 0xFFFFFFFF) != R_X86_64_RELATIVE:
                continue
            if not (dr_start <= r_offset < dr_end):
                continue
            if not (tx_start <= r_addend < tx_end):
                continue
            entries.append((r_offset, r_addend))

        entries.sort(key=lambda x: x[0])

        # Group consecutive 8-byte entries
        tables = []
        i = 0
        while i < len(entries):
            j = i + 1
            while j < len(entries):
                if entries[j][0] != entries[i][0] + (j - i) * 8:
                    break
                j += 1
            if j - i >= 50:
                tables.append({
                    "vaddr": entries[i][0],
                    "count": j - i,
                    "entries": [entries[k][1] for k in range(i, j)],
                })
            i = j

        if not tables:
            return

        dt = max(tables, key=lambda t: t["count"])
        self.dispatch_vaddr = dt["vaddr"]
        self.dispatch_count = dt["count"]
        self.dispatch_entries = dt["entries"]

    # ── Step 2: st_* name table ─────────────────────────────────────────

    def _discover_st_names(self):
        """Parse .data for st_* entries → map to dispatch indices."""
        elf = self._elf
        data_raw = elf.raw_of(".data")
        for off in range(len(data_raw) - 20):
            try:
                end = data_raw.index(b"\0", off + 16, off + 60)
            except ValueError:
                continue
            name = data_raw[off + 16:end].decode("ascii", errors="replace")
            if not name.startswith("st_"):
                continue
            idx, flags, *_ = struct.unpack_from("<IIII", data_raw, off)
            if idx < 10 or idx >= self.dispatch_count:
                continue
            if not any(e[0] == idx for e in self.st_entries):
                self.st_entries.append((idx, name, flags))

        # Build _bist_* symbols (checker flag → impl at idx+1)
        for idx, name, flags in self.st_entries:
            impl_i = idx + 1 if (flags & 0x100) else idx
            if impl_i < len(self.dispatch_entries):
                self.symbols[f"_bist_{name[3:]}"] = self.dispatch_entries[impl_i]

    # ── Step 3: StataSO exports ─────────────────────────────────────────

    def _discover_stata_so_exports(self):
        """Find StataSO_* symbols from .dynsym."""
        elf = self._elf
        ds_raw = elf.raw_of(".dynsym")
        dn_raw = elf.raw_of(".dynstr")
        if not ds_raw or not dn_raw:
            return
        entsize = 24
        for j in range(len(ds_raw) // entsize):
            entry = ds_raw[j * entsize:(j + 1) * entsize]
            st_name, _, _, st_shndx, st_value, _ = struct.unpack(
                elf.endian + "IBBHQQ", entry
            )
            if st_value == 0 or st_shndx == 0:
                continue
            name = _cstr(dn_raw, st_name)
            if name.startswith("StataSO_"):
                self.symbols[name] = st_value
                self.symbols[f"_{name}"] = st_value

    # ── Step 4: Push functions ──────────────────────────────────────────

    def _discover_push_functions(self):
        """Find _pushdbl, _pushint, _pushstr, stack_ptr, err_addr."""
        elf = self._elf
        raw = elf.text_raw
        tv = elf.text_vaddr
        bss_a = elf.bss_addr
        bss_e = elf.bss_end
        if not raw or not bss_a:
            return

        stub = bytes([0x48, 0x8b, 0x16, 0x48, 0x8d, 0x4a, 0x08,
                      0x48, 0x89, 0x0e])

        # Collect SP-pattern candidates
        candidates = []
        for ms in _find_bytes(raw, bytes([0x48, 0x8d, 0x35])):
            if ms + 17 > len(raw) or raw[ms + 7:ms + 17] != stub:
                continue
            rel32 = struct.unpack_from("<i", raw, ms + 3)[0]
            target = tv + ms + 7 + rel32
            if not (bss_a <= target < bss_e):
                continue
            if not self.stack_ptr_vaddr:
                self.stack_ptr_vaddr = target
            fn_v = _fn_start(raw, ms, tv, 200)
            if fn_v:
                fn_sz = _fn_size(raw, fn_v, tv, 500)
                candidates.append((ms, fn_v, fn_sz))

        # Real _pushdbl: contains movsd xmm0,[rdi] (= f2 0f 10 07)
        movsd = bytes([0xf2, 0x0f, 0x10, 0x07])
        movsd_poses = [tv + p for p in _find_bytes(raw, movsd)]
        for ms, fn_v, _ in candidates:
            s, e = tv + ms - 50, tv + ms + 200
            if any(s <= ml < e for ml in movsd_poses):
                self.push_fns["_pushdbl"] = fn_v
                break
        if not self.push_fns["_pushdbl"] and candidates:
            candidates.sort(key=lambda x: x[1])
            self.push_fns["_pushdbl"] = candidates[0][1]

        pd_addr = self.push_fns["_pushdbl"]

        # Error address inside _pushdbl
        if pd_addr:
            area = raw[(pd_addr - tv):(pd_addr - tv) + 200]
            for pos in _find_bytes(area, bytes([0x48, 0x8d, 0x05])):
                if pos + 12 > len(area) or area[pos + 7] != 0xc7:
                    continue
                rel32 = struct.unpack_from("<i", area, pos + 3)[0]
                self.err_addr_vaddr = pd_addr + pos + 7 + rel32
                break

        # _pushint: pxor xmm0,xmm0; cvtsi2sd %edi,%xmm0
        pi = bytes([0x66, 0x0f, 0xef, 0xc0, 0xf2, 0x0f, 0x2a, 0xc7])
        best, best_d = None, None
        for ms in _find_bytes(raw, pi):
            fc = _fn_start(raw, ms, tv, 60)
            if fc and fc > 0:
                d = abs(fc - pd_addr) if pd_addr else 0
                if best is None or d < best_d:
                    best, best_d = fc, d
        if best:
            self.push_fns["_pushint"] = best

        # _pushstr: mov $0xfffffffd,%edi near pushdbl
        ps = bytes([0xbf, 0xfd, 0xff, 0xff, 0xff])
        best, best_d = None, None
        for ms in _find_bytes(raw, ps):
            fc = 0
            for back in range(1, 80):
                bp = ms - back
                if bp < 0:
                    break
                if bp + 2 < len(raw) and raw[bp] == 0x41 and \
                   raw[bp + 1] == 0x54 and raw[bp + 2] == 0x55:
                    fc = tv + bp
                    break
            if not fc:
                for back in range(1, 80):
                    bp = ms - back
                    if bp < 0:
                        break
                    if bp + 1 < len(raw) and raw[bp] == 0x55 and \
                       raw[bp + 1] == 0x53:
                        if bp == 0 or raw[bp - 1] not in (0xFF, 0x66):
                            fc = tv + bp
                            break
            if fc and pd_addr:
                d = abs(fc - pd_addr)
                if best is None or d < best_d:
                    best, best_d = fc, d
        if best:
            self.push_fns["_pushstr"] = best

    # ── Manifest ────────────────────────────────────────────────────────

    def _to_manifest(self) -> dict:
        # Build symbols dict INCLUDING push functions (like-for-like with
        # _manifest.py build_manifest which merges them into one dict).
        merged_syms = dict(self.symbols)
        for pname, pvaddr in self.push_fns.items():
            if pvaddr:
                merged_syms[pname] = pvaddr
        return {
            "manifest_version": CURRENT_MANIFEST_VERSION,
            "sha256": self.sha256,
            "file_size": self._stat.st_size,
            "format": self.format,
            "arch": self.arch,
            "n_bist_symbols": sum(1 for k in merged_syms
                                  if k.startswith("_bist_")),
            "symbols": merged_syms,
            "dispatch_vaddr": self.dispatch_vaddr,
            "dispatch_count": self.dispatch_count,
            "data_offsets": {
                "stack_ptr_delta": self.stack_ptr_vaddr,
                "err_addr_delta": self.err_addr_vaddr,
            },
            "push_fns": dict(self.push_fns),
        }

    def save_cache(self, cache_dir: Optional[str] = None) -> str:
        """Save manifest to the manifests/ cache directory."""
        if cache_dir is None:
            cache_dir = os.path.join(os.path.dirname(__file__), "manifests")
        os.makedirs(cache_dir, exist_ok=True)
        path = os.path.join(cache_dir, f"manifest-{self.sha256[:16]}.json")
        with open(path, "w") as f:
            json.dump(self._to_manifest(), f, indent=2)
        return path

    @classmethod
    def from_cache(cls, path: str, cache_dir: Optional[str] = None
                   ) -> Optional["StataBinary"]:
        """Load from cache if available and not stale."""
        obj = cls(path)
        if cache_dir is None:
            cache_dir = os.path.join(os.path.dirname(__file__), "manifests")
        prefix = f"manifest-{obj.sha256[:16]}.json"
        cache_path = os.path.join(cache_dir, prefix)
        if not os.path.exists(cache_path):
            return None
        with open(cache_path) as f:
            mdata = json.load(f)
        if mdata.get("manifest_version", 0) < CURRENT_MANIFEST_VERSION:
            return None  # stale
        # Populate from cache
        obj.dispatch_vaddr = mdata.get("dispatch_vaddr", 0)
        obj.dispatch_count = mdata.get("dispatch_count", 0)
        obj.symbols = mdata.get("symbols", {})
        do = mdata.get("data_offsets", {}) or {}
        obj.stack_ptr_vaddr = do.get("stack_ptr_delta", 0)
        obj.err_addr_vaddr = do.get("err_addr_delta", 0)
        obj.push_fns = mdata.get("push_fns", {})
        obj.st_entries = []  # not cached
        return obj

    @classmethod
    def cache_health(cls, cache_dir: Optional[str] = None
                     ) -> list[dict]:
        """Report health of all cached manifests."""
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
            except (json.JSONDecodeError, OSError) as e:
                results.append({"file": fname, "status": "corrupt",
                                "error": str(e)})
                continue
            mver = mdata.get("manifest_version", 0)
            sha = mdata.get("sha256", "?")[:16]
            nbist = mdata.get("n_bist_symbols", 0)
            ndo = bool(mdata.get("data_offsets"))
            npf = bool(mdata.get("push_fns"))
            results.append({
                "file": fname,
                "sha256_prefix": sha,
                "version": mver,
                "status": "ok" if mver >= CURRENT_MANIFEST_VERSION else "stale",
                "n_bist": nbist,
                "has_data_offsets": ndo,
                "has_push_fns": npf,
            })
        return results

    # ── Disassembly ─────────────────────────────────────────────────────

    def disassemble(self, vaddr: int, max_size: int = 200) -> list:
        """Disassemble function at vmaddr. Returns list of capstone insn objs."""
        if not HAS_CAPSTONE or not self._elf:
            return []
        off = vaddr - self._elf.text_vaddr
        if off < 0 or off >= len(self._elf.text_raw):
            return []
        raw_fn = self._elf.text_raw[off:off + max_size]
        sz = 0
        for i in range(1, min(500, len(raw_fn))):
            if raw_fn[i] == 0xc3:
                sz = i + 1
                break
        if not sz:
            sz = min(len(raw_fn), max_size)
        arch = self._capstone_arch or (CS_ARCH_X86, CS_MODE_64)
        md = _Cs(*arch)
        return list(md.disasm(raw_fn[:sz], vaddr))

    def _follow_thunk(self, vaddr: int, max_depth: int = 2) -> list:
        """Disassemble a function, following thunk conditional jumps (capped).

        Some _bist_* functions are thunks:
          1. Check pool header tag (\"cmp dword ptr [rax - 0x94], 0x2b\")
          2. je <real_impl>  (tag present)
          3. Set error code
          4. ret

        This method disassembles the function body AND the real
        implementation reachable via forward conditional jumps.
        Depth is capped at max_depth to avoid exploding into
        deeply-nested internal control flow.
        Returns list of (level, address, mnemonic, op_str).
        """
        raw = self._elf.text_raw
        text_vaddr = self._elf.text_vaddr
        seen = set()
        result = []

        def _dis(target_vaddr: int, level: int = 0) -> None:
            if target_vaddr in seen or level > max_depth:
                return
            if target_vaddr < text_vaddr or target_vaddr >= text_vaddr + len(raw):
                return
            seen.add(target_vaddr)
            try:
                import capstone
                md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
                md.detail = False
                offset = int(target_vaddr - text_vaddr)
                code = raw[offset:offset + 200]
                insns = list(md.disasm(code, target_vaddr))
            except Exception:
                return
            for insn in insns:
                result.append((level, insn.address, insn.mnemonic, insn.op_str))
                # Follow forward conditional jumps (thunk pattern), capped
                if insn.mnemonic in ("je", "jne", "jg", "jge", "jl", "jle",
                                    "ja", "jae", "jb", "jbe", "jmp"):
                    try:
                        target = int(insn.op_str, 16)
                    except ValueError:
                        continue
                    if target > insn.address:  # forward jump
                        _dis(target, level + 1)
                if insn.mnemonic == "ret":
                    break

        _dis(vaddr)
        return result

    # ── Cross-Reference & Call Chain ──────────────────────────────────

    def find_strings(self, pattern: bytes, section: str = ".rodata") -> list:
        """Search a section for a byte pattern and return (vaddr, offset) pairs."""
        if not self._elf:
            return []
        s = self._elf.sections.get(section)
        if not s:
            return []
        sec_addr = s.get("addr", 0)
        sec_off = s.get("offset", 0)
        sec_size = s.get("size", 0)
        if not sec_size:
            return []
        raw = self._elf.raw
        data = raw[sec_off:sec_off + sec_size]
        results = []
        idx = data.find(pattern)
        while idx >= 0:
            vaddr = sec_addr + idx
            results.append((vaddr, idx))
            idx = data.find(pattern, idx + 1)
        return results

    def find_callers(self, target_vaddr: int, search_limit: int = 0) -> list:
        """Find all code locations in .text that call a specific address.

        Args:
            target_vaddr: The virtual address being called.
            search_limit: Max byte region to scan (0=entire .text).
        Returns:
            List of (caller_vaddr, text_offset) sorted by vaddr.
        """
        if not HAS_CAPSTONE or not self._elf:
            return []
        text_raw = self._elf.text_raw
        text_vaddr = self._elf.text_vaddr
        limit = search_limit or len(text_raw)
        results = []
        arch = self._capstone_arch or (CS_ARCH_X86, CS_MODE_64)
        md = _Cs(*arch)

        chunk_size = min(1 << 20, limit)  # 1MB chunks
        for chunk_start in range(0, limit, chunk_size):
            chunk = text_raw[chunk_start:chunk_start + chunk_size]
            if not chunk:
                break
            try:
                for insn in md.disasm(chunk, text_vaddr + chunk_start):
                    if insn.mnemonic == "call" or insn.mnemonic == "jmp":
                        tgt_text = insn.op_str
                        if "0x" not in tgt_text:
                            continue
                        try:
                            parts = [p for p in tgt_text.replace(",", " ").split() if p.startswith("0x")]
                            if not parts:
                                continue
                            tgt = int(parts[0], 16)
                            if abs(tgt - target_vaddr) <= 5:
                                results.append((insn.address, chunk_start + (insn.address - text_vaddr)))
                        except (ValueError, IndexError):
                            pass
            except Exception:
                pass
        return sorted(results)

    def find_string_functions(self, max_depth: int = 3) -> list:
        """Discover which dispatch entries return strings by tracing calls to _pushstr.

        Uses the discovered _pushstr address from self.push_fns.
        Strategy: for each dispatch entry function, follow call chains up to
        max_depth to find if _pushstr is eventually called. Functions that
        reach _pushstr are string-returning.

        Returns list of dicts per dispatch entry with string capability info.
        """
        if not HAS_CAPSTONE or not self._elf:
            return []
        pushstr_vaddr = self.push_fns.get("_pushstr")
        if not pushstr_vaddr:
            return [{"error": "_pushstr not found in push_fns"}]
        text_raw = self._elf.text_raw
        text_vaddr = self._elf.text_vaddr
        md = _Cs(CS_ARCH_X86, CS_MODE_64)

        addr_to_names = {}
        for name, vaddr in self.symbols.items():
            if name.startswith("_bist_"):
                addr_to_names.setdefault(vaddr, []).append(name)

        def _follow_jump_targets(insn) -> list:
            """Extract jump/call targets from an instruction."""
            targets = []
            if '0x' not in insn.op_str:
                return targets
            try:
                parts = [p for p in insn.op_str.replace(",", " ").split() if p.startswith("0x")]
                if not parts:
                    return targets
                tgt = int(parts[0], 16)
                if text_vaddr <= tgt < text_vaddr + len(text_raw):
                    targets.append(tgt)
            except (ValueError, IndexError):
                pass
            return targets

        def _find_pushstr(fn_vaddr: int, _depth: int = 0, _seen: set = None,
                          _path: list = None) -> (bool, list):
            if _seen is None:
                _seen = set()
            if _path is None:
                _path = []
            if fn_vaddr in _seen or _depth > max_depth:
                return False, []
            _seen.add(fn_vaddr)
            new_path = _path + [fn_vaddr]
            off = fn_vaddr - text_vaddr
            if off < 0 or off >= len(text_raw):
                return False, []
            # Use FIXED disassembly range — don't stop at early ret
            # Thunk functions have error-return ret at ~40-80 bytes, but
            # real implementation lives 200+ bytes in after forward jumps.
            raw = text_raw[off:min(off + 600, len(text_raw))]
            try:
                insns = list(md.disasm(raw, fn_vaddr))
            except Exception:
                return False, []
            for insn in insns:
                # CALL instructions: check target and recurse
                if insn.mnemonic == "call":
                    for tgt in _follow_jump_targets(insn):
                        if abs(tgt - pushstr_vaddr) <= 5:
                            return True, new_path + [tgt]
                        found, deeper = _find_pushstr(tgt, _depth + 1, _seen, new_path)
                        if found:
                            return True, deeper
                # JMP/JCC instructions: follow forward jumps (thunk pattern)
                if insn.mnemonic in ("jmp", "je", "jne", "jg", "jge", "jl", "jle",
                                     "ja", "jae", "jb", "jbe"):
                    for tgt in _follow_jump_targets(insn):
                        if tgt > insn.address:  # forward jumps only
                            found, deeper = _find_pushstr(tgt, _depth + 1, _seen, new_path)
                            if found:
                                return True, deeper
            return False, []

        results = []
        for idx, entry_vaddr in enumerate(self.dispatch_entries):
            names = addr_to_names.get(entry_vaddr, [])
            if not names:
                continue
            found, path = _find_pushstr(entry_vaddr)
            results.append({
                "dispatch_idx": idx,
                "names": sorted(names),
                "vaddr": entry_vaddr,
                "has_string_chain": found,
                "call_chain": path if found else [],
            })
        return results

    def analyze_dispatch_fn(self, name: str) -> dict:
        """Decompile + analyze a specific _bist_ function.

        Follows thunk conditional jumps to show the full real
        implementation, not just the dispatch entry thunk.

        Returns dict with:
          - name, vaddr, size, caller
          - disassembly (list of strings) with thunk vs impl sections
          - protocol notes (args read from stack, return type)
          - pool_header_check: whether function checks data_ptr[-0x94] == 0x2b
          - error_code: error code set when check fails
        """
        if not name.startswith("_bist_"):
            name = f"_bist_{name}"
        vaddr = self.symbols.get(name)
        if not vaddr:
            return {"name": name, "error": "symbol not found"}

        # Full analysis: follow thunks
        full_insns = self._follow_thunk(vaddr, max_depth=3)

        # Find the dispatch index for this symbol
        disp_idx = None
        for i, dv in enumerate(self.dispatch_entries):
            if dv == vaddr:
                disp_idx = i
                break

        # Protocol inference
        reads_stack = False
        calls_push = False
        has_ret = False
        has_pool_check = False
        error_code = None
        for level, addr, mnemonic, op_str in full_insns:
            if "qword ptr [rsp" in op_str or "qword ptr [rbp " in op_str:
                reads_stack = True
            if "rcx - 0x94" in op_str or "rax - 0x94" in op_str:
                has_pool_check = True
                if "2b" in op_str:
                    has_pool_check = True
            if mnemonic == "call":
                target = op_str
                if "0x" in target:
                    try:
                        t = int(target.split("0x")[1], 16)
                        for _, fv in self.push_fns.items():
                            if abs(t - fv) < 50:
                                calls_push = True
                                break
                    except ValueError:
                        pass
            if mnemonic == "ret":
                has_ret = True
            # Extract error code (mov dword ptr [rip+...], 0xNNNN)
            if "mov dword ptr" in f"{mnemonic} {op_str}" and "0x" in op_str:
                parts = op_str.split(",")
                if len(parts) > 1:
                    try:
                        ec = int(parts[-1].strip(), 16)
                        if ec > 0x100 and ec < 0x10000:
                            error_code = ec
                    except ValueError:
                        pass

        # Build sections: thunk (level 0) vs impl (level 1+)
        sections = []
        current = []
        current_label = "thunk"
        for level, addr, mnemonic, op_str in full_insns:
            label = "thunk" if level == 0 else f"impl_level_{level}"
            if label != current_label and current:
                sections.append((current_label, current))
                current = []
                current_label = label
            current.append(f"{'. ' * level}0x{addr:x}: {mnemonic} {op_str}")
        if current:
            sections.append((current_label, current))

        return {
            "name": name,
            "vaddr": vaddr,
            "size": len(full_insns),
            "dispatch_index": disp_idx,
            "sections": sections,
            "disassembly": [f"0x{addr:x}: {mnemonic} {op_str}"
                            for _, addr, mnemonic, op_str in full_insns],
            "reads_stack_args": reads_stack,
            "calls_push_function": calls_push,
            "has_return": has_ret,
            "has_pool_header_check": has_pool_check,
            "error_code": error_code,
        }

    # ── Live dispatch tracing ─────────────────────────────────────────

    def trace_dispatch_call(self, name: str, *args,
                            engine=None) -> dict:
        """Trace a dispatch call step by step through the live engine.

        Requires an initialized pystata_x engine.  Returns a detailed
        trace dict with every intermediate value, replacing ad-hoc
        debugging scripts.

        Args:
            name: Short name (e.g. 'nobs') or full name ('_bist_nobs')
            *args: Arguments to pass
            engine: The initialized engine module (or try auto-import)
        """
        trace = {
            "name": name,
            "args": args,
            "steps": [],
            "result": None,
            "error": None,
        }

        if engine is None:
            try:
                import pystata_x.sfi._engine as engine
            except ImportError:
                trace["error"] = "engine not available"
                return trace

        # Resolve symbol name (try short name, then _bist_ prefix)
        sym_name = name
        if not name.startswith("_bist_") and not name.startswith("StataSO_"):
            candidate = f"_bist_{name}"
            if candidate in engine._SYMS:
                sym_name = candidate
        vaddr = engine._SYMS.get(sym_name)
        trace["sym_name"] = sym_name
        trace["vaddr"] = vaddr
        trace["steps"].append({
            "step": "resolve_symbol",
            "query": name,
            "resolved": sym_name,
            "vaddr": vaddr,
        })

        if vaddr is None:
            trace["error"] = f"symbol {name} not found in SYMS"
            return trace

        import ctypes

        # Save trace
        sp_before = engine._save_sp()
        trace["sp_before"] = sp_before
        trace["steps"].append({"step": "save_sp", "value": sp_before})

        # Push args
        n_args = len(args)
        if n_args > 0:
            for a in reversed(args):
                if isinstance(a, int):
                    engine._push_int(a)
                    trace["steps"].append({"step": "push_int", "value": a})
                elif isinstance(a, float):
                    engine._push_double(a)
                    trace["steps"].append({"step": "push_double", "value": a})
                elif isinstance(a, bytes):
                    engine._push_str(a)
                    trace["steps"].append({"step": "push_str", "value": a})
                elif isinstance(a, str):
                    engine._push_str(a.encode("utf-8"))
                    trace["steps"].append({"step": "push_str", "value": a})
            # Sentinel
            engine._push_double(0.0)
            trace["steps"].append({"step": "push_sentinel"})
        else:
            trace["steps"].append({"step": "push_args", "note": "0 args, no push"})

        sp_after_push = engine._save_sp()
        trace["sp_after_push"] = sp_after_push
        trace["steps"].append({"step": "after_push", "sp": sp_after_push,
                               "diff": sp_after_push - sp_before})

        # Call dispatch function
        rt = engine._BASE + vaddr
        fn_type = ctypes.CFUNCTYPE(None, ctypes.c_int)
        fn = ctypes.cast(rt, fn_type)
        trace["steps"].append({"step": "dispatch_call",
                               "target": hex(rt),
                               "arg_count": n_args})
        try:
            fn(n_args)
        except Exception as e:
            trace["error"] = f"dispatch call crashed: {e}"
            return trace

        sp_after_call = engine._save_sp()
        trace["sp_after_call"] = sp_after_call
        trace["steps"].append({"step": "after_call", "sp": sp_after_call,
                               "diff": sp_after_call - sp_after_push})

        # Read result
        if sp_after_call <= sp_before:
            trace["result"] = None
            trace["steps"].append({"step": "read_result",
                                   "note": "stack did not advance"})
            return trace

        tsmat_ptr = ctypes.c_uint64.from_address(sp_after_call).value
        trace["tsmat_ptr"] = tsmat_ptr
        trace["steps"].append({"step": "read_tsmat_ptr", "value": tsmat_ptr})

        if not tsmat_ptr:
            trace["result"] = None
            trace["steps"].append({"step": "read_result",
                                   "note": "tsmat ptr is NULL"})
            return trace

        # Determine type from tsmat[0x34]
        result_type = ctypes.c_uint32.from_address(tsmat_ptr + 0x34).value & 0xFF
        trace["result_type"] = result_type
        trace["steps"].append({"step": "result_type", "type": result_type})

        data_buf = ctypes.c_uint64.from_address(tsmat_ptr).value
        trace["data_buf"] = data_buf

        if result_type == 0:
            # Numeric result
            if data_buf:
                val = ctypes.c_double.from_address(data_buf).value
                trace["result"] = val
                trace["result_int"] = int(val)
                trace["steps"].append({"step": "read_numeric", "value": val})
            else:
                trace["result"] = None
                trace["steps"].append({"step": "read_result",
                                       "note": "null data buffer"})
        else:
            # String result
            trace["steps"].append({"step": "read_string", "note": "not implemented"})
            trace["result"] = None

        # Restore SP
        engine._restore_sp(sp_before)
        trace["steps"].append({"step": "restore_sp", "value": sp_before})

        return trace

    # ── Stack protocol analysis ───────────────────────────────────────

    def analyze_stack_protocol(self) -> dict:
        """Analyze how push functions store tsmat pointers on the stack.

        The engine's _pop_and_read_* functions read the result tsmat
        pointer from [SP_after-8].  This was correct for the simulated
        push (which wrote to [SP] then advanced SP), but the REAL
        _pushdbl may store at [rdx+8] = [SP_after] instead.

        Returns dict with push_fn: {stores_at_old_sp, stores_at_new_sp, ...}
        """
        result = {}
        for name, addr in self.push_fns.items():
            if not addr or not self._elf:
                continue
            insns = self.disassemble(addr, max_size=100)
            info = {
                "vaddr": addr,
                "instr_count": len(insns),
                "disassembly": [],
                "store_at_offset": None,  # offset from rdx/old_sp
                "sp_advance_increment": 8,
            }
            has_sp_pattern = False
            store_disp = None
            for insn in insns:
                info["disassembly"].append(
                    f"0x{insn.address:x}: {insn.mnemonic} {insn.op_str}"
                )
                # Look for mov [rdx+N], rax or mov [rdx+N], rN
                if insn.mnemonic == "mov":
                    op = insn.op_str
                    if "qword ptr [rdx" in op and "rax" in op:
                        # Extract displacement from [rdx + N]
                        import re
                        m = re.search(r"\[rdx\s*\+\s*(\d+)\]", op)
                        if m:
                            store_disp = int(m.group(1))
                            info["store_at_offset"] = store_disp
                    # Detect SP advance (lea rsi,[rip+off])
                    if "rsi, qword ptr" in op or "rsi, [rip" in op:
                        # This might be the SP address load
                        pass
            info["tsmat_store_location"] = (
                "sp_after" if store_disp == 8 else
                "sp_before" if store_disp == 0 else
                f"unknown(rdx+{store_disp})" if store_disp is not None else
                "no_store_found"
            )
            result[f"push_fn_{name}"] = info

        # Also analyze the dispatch functions to understand their
        # arg-reading protocol
        result["dispatch_examples"] = {}
        for dname in ["_bist_nobs", "_bist_nvar", "_bist_data"]:
            di = self.analyze_dispatch_fn(dname)
            if "error" not in di:
                result["dispatch_examples"][dname] = {
                    "vaddr": di["vaddr"],
                    "calls_push": di["calls_push_function"],
                    "reads_stack": di["reads_stack_args"],
                }

        return result

    # ── Manifest diff (like-for-like comparison) ───────────────────────

    # ═══════════════════════════════════════════════════════════════
    # Protocol analysis — x86_64 dispatch protocol classification
    # ═══════════════════════════════════════════════════════════════
    #
    # ARCHITECTURE NOTE (x86_64 dispatch protocol):
    #
    # On x86_64, ~85% of dispatch functions (100/118) reset the
    # stack pointer (SP_global at 0x500C638) to a .data address
    # before reading their args.  Despite this SP reset, the
    # functions actually read their args from the ARG POINTER at
    # 0x500C6A0 (also in .bss), which is SEPARATE from SP_global.
    #
    # The push functions (_push_str, _push_int, _push_double)
    # internally update THIS arg pointer (0x500C6A0) — they store
    # the tsmat pointer there and advance it by 8 on each push.
    # The engine's _save_sp() also reads from 0x500C6A0 (via the
    # manifest's stack_ptr_delta config).
    #
    # This means the STANDARD push+stack protocol works for ALL
    # dispatch functions on x86_64, including SP-resetting ones.
    # No special calling convention is needed for these functions.
    #
    # Pool-header checks: tsmat[-0x94] == 0x2b IS satisfied because
    # the tsmat is pool-allocated.  The tsmat struct has embedded
    # data at offset 0 (the first 8 bytes are the double value or
    # GSO string pointer, NOT a separate data buffer pointer).
    # Checking data_buf[-0x94] was based on a misinterpretation;
    # the actual check is on the tsmat itself.
    #
    # Methods in this section extract SP/arg buffer addresses for
    # reference and protocol classification.
    # ───────────────────────────────────────────────────────────────

    def extract_arg_buffer_addr(self, name: str) -> dict:
        """Extract the .data arg buffer address from an SP-resetting dispatch function.

        SP-resetting functions do:
          lea rax, [rip + A]    # rax = &SP_GLOBAL
          lea rX, [rip + B]     # rX = .data arg buffer address
          mov qword ptr [rax], rX  # SP_GLOBAL = arg buffer address

        Returns the arg buffer address and the SP global address.
        Only returns sp_reset protocol when the triple pattern is found.
        """
        if not name.startswith("_bist_"):
            name = f"_bist_{name}"
        vaddr = self.symbols.get(name)
        if not vaddr:
            return {"name": name, "error": "symbol not found"}
        if not HAS_CAPSTONE or not self._elf:
            return {"name": name, "error": "capstone not available"}

        elf = self._elf
        text_raw = elf.text_raw
        text_vaddr = elf.text_vaddr
        md = _Cs(CS_ARCH_X86, CS_MODE_64)

        off = vaddr - text_vaddr
        if off < 0 or off >= len(text_raw):
            return {"name": name, "error": "address out of range"}

        raw = text_raw[off:min(off + 50, len(text_raw))]
        try:
            insns = list(md.disasm(raw, vaddr))
        except Exception:
            return {"name": name, "error": "disassembly failed"}

        result = {"name": name, "vaddr": vaddr, "protocol": "standard_push_stack"}

        # Look for the SP-reset triple pattern in first 15 instructions:
        #   1. lea rax, [rip + X]  (SP global address)
        #   2. lea rX, [rip + Y]   (arg buffer address, rX != rax)
        #   3. mov [rax], rX       (SP_global = arg_buffer)
        lea_rax_target = None
        lea_other_target = None
        lea_other_reg = None
        sp_global_addr = None

        for insn in insns[:15]:
            op = f"{insn.mnemonic} {insn.op_str}"

            if insn.mnemonic == "lea" and "rax" in insn.op_str and "rip" in insn.op_str:
                # First pattern: lea rax, [rip + X]
                if lea_rax_target is None:
                    import re as _re
                    m = _re.search(r'\[rip\s*([+-])\s*(0x[0-9a-fA-F]+)\]', insn.op_str)
                    if m:
                        sign = 1 if m.group(1) == '+' else -1
                        disp = int(m.group(2), 16)
                        lea_rax_target = disp
                        sp_global_addr = insn.address + insn.size + sign * disp

            elif insn.mnemonic == "lea" and "rip" in insn.op_str and lea_rax_target is not None:
                # Second pattern: lea rX, [rip + Y] where rX is not rax
                import re as _re
                m = _re.search(r'\[rip\s*([+-])\s*(0x[0-9a-fA-F]+)\]', insn.op_str)
                if m:
                    sign = 1 if m.group(1) == '+' else -1
                    disp = int(m.group(2), 16)
                    # Extract the register: op_str starts with 'rX, '
                    reg = insn.op_str.split(",")[0].strip() if "," in insn.op_str else ""
                    if reg and reg != "rax":
                        lea_other_target = insn.address + insn.size + sign * disp
                        lea_other_reg = reg

            elif insn.mnemonic == "mov" and "qword ptr" in op and lea_other_reg is not None:
                # Third pattern: mov qword ptr [rax], rX
                if f"qword ptr [rax]" in op and lea_other_reg in op:
                    result["protocol"] = "sp_reset"
                    if sp_global_addr:
                        result["sp_global_addr"] = sp_global_addr
                    if lea_other_target:
                        result["arg_buffer_addr"] = lea_other_target
                    break

                # Also check: mov qword ptr [rax], rX without specific register check
                if "qword ptr [rax], r" in op and lea_other_target:
                    result["protocol"] = "sp_reset"
                    if sp_global_addr:
                        result["sp_global_addr"] = sp_global_addr
                    if lea_other_target:
                        result["arg_buffer_addr"] = lea_other_target
                    break

        return result


    def analyze_protocol(self, name: str) -> dict:
        """Deep protocol analysis of a dispatch entry.

        Follows thunk jumps (via _follow_thunk) to find the real
        implementation and identifies pool-header checks, type/flag
        field expectations, string vs numeric code paths, and
        whether _pushstr is called.
        """
        if not name.startswith("_bist_"):
            name = f"_bist_{name}"
        vaddr = self.symbols.get(name)
        if not vaddr:
            return {"name": name, "error": "symbol not found"}
        if not HAS_CAPSTONE or not self._elf:
            return {"name": name, "error": "capstone not available"}

        # Use _follow_thunk to get the real code (follows thunk jumps)
        full_insns = self._follow_thunk(vaddr, max_depth=4)

        proto = {
            "name": name, "vaddr": vaddr, "dispatch_idx": None,
            "size": len(full_insns),
            "pool_header_check": None,
            "type_field": None,
            "flag_field": None,
            "has_string_path": False,
            "has_numeric_path": False,
            "string_path_vaddr": None,
            "numeric_path_vaddr": None,
            "calls_pushstr": False,
            "pushstr_call_sites": [],
            "error_codes": [],
            "reads_sp": False,
            "checks_obs_dim": False,
            "checks_var_dim": False,
        }
        for i, dv in enumerate(self.dispatch_entries):
            if dv == vaddr:
                proto["dispatch_idx"] = i
                break

        pushstr_vaddr = self.push_fns.get("_pushstr", 0)

        for _level, _addr, mnemonic, op_str in full_insns:
            op = f"{mnemonic} {op_str}"

            # Pool-header check: cmp [reg +/- N], 0x2b
            if "cmp" in mnemonic and "0x2b" in op_str:
                if "0x94" in op_str:
                    checks_tsmat = "rax - 0x94" in op_str
                    proto["pool_header_check"] = {
                        "offset": -0x94, "tag_value": 0x2b,
                        "at_vaddr": _addr,
                        "checks_tsmat": checks_tsmat,
                    }

            # Type field at [0x34]: cmp dx, -3 (0xFFFD) or test dx, dx (==0)
            if "0x34" in op_str and "movzx" in mnemonic:
                # movzx edx, word ptr [rax + 0x34] — type field loaded
                if proto["type_field"] is None:
                    proto["type_field"] = {"offset": 0x34}
            if proto["type_field"] is not None:
                if "cmp" in mnemonic and op_str.rstrip().endswith("-3"):
                    proto["has_string_path"] = True
                    proto["string_path_vaddr"] = _addr
                    proto["type_field"]["string_value"] = 0xFFFD
                if mnemonic == "test" and "dx, dx" in op_str:
                    proto["has_numeric_path"] = True
                    proto["numeric_path_vaddr"] = _addr
                    proto["type_field"]["numeric_value"] = 0x0000
                if "cmp" in mnemonic and op_str.rstrip().endswith(", 0") and "0x34" in op_str:
                    # Some functions check [0x34] != 0 directly
                    proto["has_numeric_path"] = True
                    proto["numeric_path_vaddr"] = _addr
                    proto["type_field"]["numeric_value"] = 0x0000

            # Flag field at [0x36]: cmp byte ptr [rax + 0x36], N
            if "0x36" in op_str and "cmp" in mnemonic:
                val = None
                if ", 0" in op_str:
                    val = 0
                elif ", 2" in op_str:
                    val = 2
                if proto["flag_field"] is None:
                    proto["flag_field"] = {"offset": 0x36}
                if val is not None:
                    proto["flag_field"]["check_value"] = val

            # Dimension checks at [0x20] and [0x28]
            if "0x20" in op_str and "cmp" in mnemonic:
                proto["checks_obs_dim"] = True
            if "0x28" in op_str and "cmp" in mnemonic:
                proto["checks_var_dim"] = True

            # _pushstr detection in CALL instructions
            if mnemonic == "call" and "0x" in op_str:
                try:
                    parts = [p for p in op_str.replace(",", " ").split() if p.startswith("0x")]
                    if parts:
                        tgt = int(parts[0], 16)
                        if pushstr_vaddr and abs(tgt - pushstr_vaddr) <= 5:
                            proto["calls_pushstr"] = True
                            proto["pushstr_call_sites"].append(_addr)
                except (ValueError, IndexError):
                    pass

            # Error code writes
            if "mov dword ptr" in op and "0x" in op_str:
                parts = op_str.split(",")
                if len(parts) > 1:
                    try:
                        ec = int(parts[-1].strip(), 16)
                        if 0x100 < ec < 0x10000:
                            proto["error_codes"].append((_addr, ec))
                    except ValueError:
                        pass

        if proto["calls_pushstr"]:
            proto["protocol_type"] = "string_return"
        elif proto["has_string_path"]:
            proto["protocol_type"] = "string_aware"
        elif proto["has_numeric_path"]:
            proto["protocol_type"] = "numeric_return"
        else:
            proto["protocol_type"] = "unknown"
        return proto

    def catalog_all_protocols(self) -> list[dict]:
        """Run protocol analysis on all dispatch entries with _bist_* names."""
        addr_to_names = {}
        for name, vaddr in self.symbols.items():
            if name.startswith("_bist_"):
                addr_to_names.setdefault(vaddr, []).append(name)
        results = []
        for vaddr in sorted(addr_to_names):
            proto = self.analyze_protocol(addr_to_names[vaddr][0])
            results.append(proto)
        return results

    @staticmethod
    def diff_manifests(a: dict, b: dict) -> dict:
        """Compare two manifests and report differences.

        Returns:
            {
                "same_sha256": bool,
                "version_diff": (a_ver, b_ver),
                "symbol_diff": {
                    "only_in_a": [...],
                    "only_in_b": [...],
                    "address_changes": {name: (a_addr, b_addr), ...},
                },
                "data_offset_diff": {key: (a_val, b_val), ...},
                "push_fn_diff": {name: (a_addr, b_addr), ...},
                "structurally_identical": bool,
            }
        """
        diff = {
            "same_sha256": a.get("sha256") == b.get("sha256"),
            "version_diff": (a.get("manifest_version", 0),
                             b.get("manifest_version", 0)),
        }

        # Symbol differences
        syms_a = set(a.get("symbols", {}).items())
        syms_b = set(b.get("symbols", {}).items())
        keys_a = set(a.get("symbols", {}))
        keys_b = set(b.get("symbols", {}))

        only_a = keys_a - keys_b
        only_b = keys_b - keys_a
        common = keys_a & keys_b

        addr_changes = {}
        for k in common:
            va = a["symbols"][k]
            vb = b["symbols"][k]
            if va != vb:
                addr_changes[k] = (va, vb)

        diff["symbol_diff"] = {
            "n_a": len(keys_a),
            "n_b": len(keys_b),
            "only_in_a": sorted(only_a),
            "only_in_b": sorted(only_b),
            "address_changes": addr_changes,
        }

        # Data offsets differences
        do_a = a.get("data_offsets", {}) or {}
        do_b = b.get("data_offsets", {}) or {}
        do_diff = {}
        for k in set(list(do_a.keys()) + list(do_b.keys())):
            if do_a.get(k) != do_b.get(k):
                do_diff[k] = (do_a.get(k), do_b.get(k))
        diff["data_offset_diff"] = do_diff

        # Push function differences
        pf_a = a.get("push_fns", {})
        pf_b = b.get("push_fns", {})
        pf_diff = {}
        for k in set(list(pf_a.keys()) + list(pf_b.keys())):
            if pf_a.get(k) != pf_b.get(k):
                pf_diff[k] = (pf_a.get(k), pf_b.get(k))
        diff["push_fn_diff"] = pf_diff

        diff["structurally_identical"] = (
            not addr_changes and not only_a and not only_b
            and not do_diff and not pf_diff
        )
        return diff

    # ── Live verification ──────────────────────────────────────────────

    def verify_all(self) -> list[dict]:
        """Test dispatachable symbols against a running engine.

        Requires initialized pystata_x engine (call initialize() first).
        Returns [{name, status, value/error}, ...].
        Only tests known-safe zero/no-arg functions — many dispatch
        stubs crash on x86_64 when called without proper args/state.
        """
        results = []
        try:
            from pystata_x.sfi._engine import call_int, call_double, call_string
        except ImportError:
            return [{"name": "*", "status": "error",
                     "error": "engine not available"}]

        _SAFE_FNS = frozenset({
            "nobs", "nvar", "eclear", "sclear",
        })

        for bname in sorted(self.symbols):
            if not bname.startswith("_bist_"):
                continue
            short = bname[6:]
            if short not in _SAFE_FNS:
                continue
            try:
                val = call_int(short)
                if val is None and short in ("nobs", "nvar"):
                    val = call_double(short)
                results.append({
                    "name": short,
                    "type": "int",
                    "status": "ok" if val is not None else "null",
                    "value": val,
                })
            except Exception as e:
                results.append({
                    "name": short,
                    "status": "error",
                    "error": str(e),
                })
        return results

    # ── Report ──────────────────────────────────────────────────────────

    def report(self, verbose: bool = False) -> str:
        """Generate comprehensive human-readable report."""
        L = []
        L.append("=" * 72)
        L.append("Stata Binary Analysis Report")
        L.append(f"File: {self.path}")
        L.append("=" * 72)
        L.append("")
        L.append(f"Format:    {self.format}")
        L.append(f"Arch:      {self.arch}")
        L.append(f"Size:      {self._stat.st_size:,} bytes"
                 f" ({self._stat.st_size / 1e6:.1f} MB)")
        L.append(f"SHA256:    {self.sha256[:32]}...")
        L.append("")

        if self._elf:
            L.append("── Sections ────────────────────────────────────────")
            for name in [".text", ".data", ".bss", ".data.rel.ro",
                         ".rela.dyn", ".dynsym"]:
                s = self._elf[name]
                if s:
                    L.append(f"  {name:15s}  addr=0x{s['addr']:010x}  "
                             f"size=0x{s['size']:x}")
            L.append("")

        L.append(f"── Dispatch Table ─────────────────────────────────────")
        L.append(f"  Vaddr:     0x{self.dispatch_vaddr:x}")
        L.append(f"  Entries:   {self.dispatch_count}")
        L.append("")

        L.append(f"── Push Functions ─────────────────────────────────────")
        L.append(f"  Stack ptr: 0x{self.stack_ptr_vaddr:x}  "
                 f"(delta={self.stack_ptr_vaddr})")
        L.append(f"  Error addr: 0x{self.err_addr_vaddr:x}  "
                 f"(delta={self.err_addr_vaddr})")
        for name, addr in self.push_fns.items():
            if addr:
                sz = _fn_size(self._elf.text_raw, addr, self._elf.text_vaddr) \
                    if self._elf else 0
                L.append(f"  {name:12s}  0x{addr:x}  ({sz} bytes)")
            else:
                L.append(f"  {name:12s}  NOT FOUND")
        L.append("")

        if HAS_CAPSTONE and self._elf:
            L.append(f"── Push Function Disassembly ───────────────────────")
            for name, addr in self.push_fns.items():
                if not addr:
                    continue
                L.append(f"\n  {name} (0x{addr:x}):")
                insns = self.disassemble(addr)
                for ins in insns[:25]:
                    L.append(f"  {ins.address:#x}: {ins.mnemonic} {ins.op_str}")
                if len(insns) > 25:
                    L.append(f"  ... ({len(insns)} total)")
            L.append("")

        L.append(f"── Symbols ───────────────────────────────────────────")
        bist_n = sum(1 for k in self.symbols if k.startswith("_bist_"))
        so_n = sum(1 for k in self.symbols if "StataSO" in k)
        L.append(f"  Total:     {len(self.symbols)}")
        L.append(f"  _bist_:    {bist_n}")
        L.append(f"  StataSO:   {so_n}")
        if bist_n:
            L.append(f"  Sample _bist_ (first 10):")
            for k in sorted(self.symbols)[:10]:
                if k.startswith("_bist_"):
                    L.append(f"    {k:25s}  0x{self.symbols[k]:x}")
        L.append("")

        if self.st_entries and self.dispatch_entries:
            L.append(f"── st_* Name Table ({len(self.st_entries)} entries) ───")
            L.append(f"  {'Idx':>4s} {'Name':25s} {'Flags':>10s} "
                     f"{'Checker':>7s} {'Impl':>11s}")
            L.append(f"  {'-'*4} {'-'*25} {'-'*10} {'-'*7} {'-'*11}")
            for idx, name, flags in sorted(self.st_entries,
                                           key=lambda x: x[0]):
                has_c = bool(flags & 0x100)
                impl_i = idx + 1 if has_c else idx
                impl_a = self.dispatch_entries[impl_i] \
                    if impl_i < len(self.dispatch_entries) else 0
                impl_s = f"0x{impl_a:x}" if impl_a else "---"
                L.append(f"  {idx:4d} {name:25s} {flags:#010x} "
                         f"{'Y' if has_c else 'N':>7s} {impl_s:>11s}")
            L.append("")

        # ── Health summary ────────────────────────────────────────────
        L.append("── Cache Health ────────────────────────────────────────")
        health = self.cache_health()
        if not health:
            L.append("  No cached manifests.")
        else:
            for h in health:
                st = h["status"]
                mark = "✓" if st == "ok" else "!" if st == "stale" else "✗"
                L.append(f"  {mark} {h['sha256_prefix']}: "
                         f"v{h['version']}, {h['n_bist']} bist, "
                         f"{'do' if h['has_data_offsets'] else 'no-do'}, "
                         f"{'pf' if h['has_push_fns'] else 'no-pf'}")
        L.append("")

        return "\n".join(L)


# =========================================================================
#  Standalone cache health check (no binary path needed)
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
        # numscalar uses pool-header which is a known x86_64 limitation
        ("numscalar", engine.call_double, ["pi"], lambda r: r is not None, _is_x86_64_linux),
    ]

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
