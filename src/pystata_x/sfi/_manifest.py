"""_manifest.py — Cross-platform symbol table discovery and manifest management.

Provides platform-specific ELF / Mach-O / PE binary parsing to extract
function vmaddrs from Stata's shared library, cached in manifest.json.

Architecture
------------
At init time, the engine computes SHA256 of the loaded Stata shared library
and looks up known symbol tables in manifest.json (keyed by file hash).

If found → use pre-computed vmaddrs (fast, no parsing needed).
If not found → dynamically parse the binary (Mach-O/ELF/PE) to discover all
relevant symbols, and optionally update manifest for future sessions.

Platform support
----------------
- **macOS**: Mach-O symbol table via fat binary + thin Mach-O nlist parsing
- **Linux**:   ELF symbol table via section headers
- **Windows**: PE export address table + COFF symbol table
"""
import ctypes
import hashlib
import json
import os
import platform as _platform
import struct
import sys
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
#  Manifest loading
# ---------------------------------------------------------------------------

_MANIFEST: dict = {}
_HERE = Path(__file__).parent
_MANIFEST_PATH = _HERE / "manifest.json"


def _load_manifest() -> dict:
    global _MANIFEST
    if _MANIFEST:
        return _MANIFEST
    if _MANIFEST_PATH.exists():
        with open(_MANIFEST_PATH) as f:
            _MANIFEST = json.load(f)
    return _MANIFEST


def _save_manifest(m: dict) -> None:
    global _MANIFEST
    _MANIFEST = m
    with open(_MANIFEST_PATH, "w") as f:
        json.dump(m, f, indent=2)


# ---------------------------------------------------------------------------
#  File hashing
# ---------------------------------------------------------------------------


def file_sha256(path: str) -> str:
    """Compute SHA256 of a file (64-char hex string)."""
    h = hashlib.sha256()
    with open(path, "rb", buffering=1048576) as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
#  String helpers
# ---------------------------------------------------------------------------


def _read_cstr(buf: bytes, offset: int) -> str:
    """Read null-terminated string from buffer at offset."""
    end = buf.find(b"\0", offset)
    if end == -1:
        return buf[offset:].decode("utf-8", errors="replace")
    return buf[offset:end].decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
#  Mach-O constants
# ---------------------------------------------------------------------------

CPU_TYPE_ARM64 = 0x0100000C
CPU_TYPE_X86_64 = 0x01000007
MH_MAGIC_64 = 0xFEEDFACF
MH_CIGAM_64 = 0xCFFEEDFE
FAT_MAGIC = 0xCAFEBABE
FAT_CIGAM = 0xBEBAFECA


def _current_macho_cputype() -> int:
    """Return the Mach-O cputype matching the current Python process."""
    m = _platform.machine()
    if m.startswith("arm64") or m == "aarch64":
        return CPU_TYPE_ARM64
    return CPU_TYPE_X86_64


# ---------------------------------------------------------------------------
#  Mach-O symbol table reader (macOS)
# ---------------------------------------------------------------------------


def _read_macho_syms(path: str, arch: Optional[str] = None) -> dict[str, int]:
    """Parse Mach-O symbol table from a .dylib file.

    Handles both thin Mach-O files and fat (universal) binaries.
    For fat binaries, auto-selects the slice matching the current arch
    unless *arch* is specified ("arm64" or "x86_64").

    Returns dict {sym_name: vmaddr}.
    Only exports non-stab symbols with n_type & N_EXT.
    """
    with open(path, "rb") as f:
        magic_raw = f.read(4)
    magic_le = struct.unpack("<I", magic_raw)[0]

    # ---- Determine if fat binary ----
    # Fat (universal) header is always big-endian, regardless of whether
    # the file appears as FAT_MAGIC (BE 0xCAFEBABE) or FAT_CIGAM (LE swap).
    fat_endian = None
    if magic_le == FAT_CIGAM or struct.unpack(">I", magic_raw)[0] == FAT_MAGIC:
        fat_endian = ">"

    if fat_endian is not None:
        with open(path, "rb") as f:
            f.read(4)  # skip magic
            narch = struct.unpack(fat_endian + "I", f.read(4))[0]

            # Determine target CPU type
            if arch is None:
                target_cputype = _current_macho_cputype()
            elif arch == "arm64":
                target_cputype = CPU_TYPE_ARM64
            elif arch == "x86_64":
                target_cputype = CPU_TYPE_X86_64
            else:
                raise ValueError(f"Unknown arch: {arch}")

            slice_offset = -1
            slice_size = 0
            for i in range(narch):
                cputype = struct.unpack(fat_endian + "I", f.read(4))[0]
                f.read(4)  # cpusubtype
                offset = struct.unpack(fat_endian + "I", f.read(4))[0]
                size = struct.unpack(fat_endian + "I", f.read(4))[0]
                f.read(4)  # align
                # Match exact cputype (the ARM64 mask variant handling
                # is for the case when cpusubtype differs)
                if cputype == target_cputype or \
                   (target_cputype == CPU_TYPE_ARM64 and (cputype & 0x00FFFFFF) == 12) or \
                   (target_cputype == CPU_TYPE_X86_64 and (cputype & 0x00FFFFFF) == 7):
                    slice_offset = offset
                    slice_size = size
                    break

            if slice_offset < 0:
                raise ValueError(f"No slice for target CPU (cputype=0x{target_cputype:08x}) in fat binary")

            return _parse_thin_macho(path, slice_offset)

    # ---- Thin Mach-O (single arch) ----
    return _parse_thin_macho(path, 0)


def _parse_thin_macho(path: str, file_offset: int) -> dict[str, int]:
    """Parse a thin Mach-O 64-bit symbol table starting at file_offset."""
    with open(path, "rb") as f:
        f.seek(file_offset)
        magic_raw = f.read(4)
        magic_le = struct.unpack("<I", magic_raw)[0]

        if magic_le == MH_CIGAM_64:
            endian = ">"
        elif magic_le == MH_MAGIC_64:
            endian = "<"
        else:
            raise ValueError(
                f"Not a Mach-O 64-bit file at offset 0x{file_offset:x}: "
                f"magic=0x{magic_le:08X}"
            )

        f.seek(file_offset + 4)
        cputype = struct.unpack(endian + "I", f.read(4))[0]
        f.read(4)  # cpusubtype
        filetype = struct.unpack(endian + "I", f.read(4))[0]
        ncmds = struct.unpack(endian + "I", f.read(4))[0]
        f.read(4 + 4 + 4)  # sizeofcmds + flags + reserved (32-byte header)

        if filetype != 6:  # MH_DYLIB
            raise ValueError(f"Not a dylib (filetype={filetype})")

        symtab_off = 0
        symtab_nsyms = 0
        strtab_off = 0
        strtab_size = 0

        for _ in range(ncmds):
            cmd_start = f.tell()
            lc_cmd, lc_cmdsize = struct.unpack(endian + "II", f.read(8))

            if lc_cmd == 0x2:  # LC_SYMTAB
                symoff, nsyms, stroff, strsize = struct.unpack(
                    endian + "IIII", f.read(16)
                )
                # symoff/stroff are relative to the Mach-O start (slice offset)
                symtab_off = file_offset + symoff
                symtab_nsyms = nsyms
                strtab_off = file_offset + stroff
                strtab_size = strsize
                break
            f.seek(cmd_start + lc_cmdsize)

    if symtab_off == 0:
        return {}

    with open(path, "rb") as f:
        f.seek(strtab_off)
        strtab = f.read(strtab_size)

        f.seek(symtab_off)
        symbols = {}
        for _ in range(symtab_nsyms):
            entry = f.read(16)
            if len(entry) < 16:
                break
            (n_strx, n_type, n_sect, n_desc, n_value) = struct.unpack(
                endian + "IBBhQ", entry
            )

            # Skip stab entries and undefined symbols
            if n_type & 0xE0:
                continue
            if n_value == 0:
                continue

            name = _read_cstr(strtab, n_strx)
            if name:
                symbols[name] = n_value

    return symbols


# ---------------------------------------------------------------------------
#  ELF symbol table reader (Linux)
# ---------------------------------------------------------------------------


def _read_elf_syms(path: str) -> dict[str, int]:
    """Parse ELF64 symbol table from a .so file.

    Tries .symtab first (un-stripped binaries), falls back to .dynsym.
    Returns dict {sym_name: st_value (vmaddr)}.
    """
    with open(path, "rb") as f:
        ident = f.read(16)
        if ident[:4] != b"\x7fELF":
            raise ValueError("Not an ELF file")

        ei_class = ident[4]
        ei_data = ident[5]

        if ei_class != 2:  # ELFCLASS64
            raise ValueError("Not 64-bit ELF")
        endian = "<" if ei_data == 1 else ">"

        f.seek(0)
        ehdr = f.read(64)
        (e_ident, e_type, e_machine, e_version, e_entry,
         e_phoff, e_shoff, e_flags, e_ehsize, e_phentsize,
         e_phnum, e_shentsize, e_shnum, e_shstrndx) = struct.unpack(
            endian + "16sHHIIQQQIHHHH", ehdr
        )

        # Read section header string table
        f.seek(e_shoff + e_shstrndx * e_shentsize)
        shstr_ent = f.read(e_shentsize)
        (sh_name, sh_type, sh_flags, sh_addr, sh_offset,
         sh_size, sh_link, sh_info, sh_addralign, sh_entsize) = \
            struct.unpack(endian + "IIQQQQIIQQ", shstr_ent)
        f.seek(sh_offset)
        shstrtab = f.read(sh_size)

        sections = {}
        for i in range(e_shnum):
            f.seek(e_shoff + i * e_shentsize)
            shdr = f.read(64)
            if len(shdr) < 64:
                break
            (sh_name, sh_type, sh_flags, sh_addr, sh_offset_v,
             sh_size, sh_link, sh_info, sh_addralign, sh_entsize) = \
                struct.unpack(endian + "IIQQQQIIQQ", shdr)
            name = _read_cstr(shstrtab, sh_name)
            sections[name] = {
                "type": sh_type,
                "addr": sh_addr,
                "offset": sh_offset_v,
                "size": sh_size,
                "entsize": sh_entsize,
            }

        symbols = {}

        strtab_info = sections.get(".strtab")
        symtab_info = sections.get(".symtab")
        dynstr_info = sections.get(".dynstr")
        dynsym_info = sections.get(".dynsym")

        def _read_elf_symtab(strtab_off, strtab_sz, symtab_off, entsize, nsyms):
            """Read ELF64 symbol table entries."""
            syms = {}
            with open(path, "rb") as f2:
                f2.seek(strtab_off)
                strtab = f2.read(strtab_sz)
                f2.seek(symtab_off)
                for j in range(nsyms):
                    entry = f2.read(entsize)
                    if len(entry) < 24:
                        break
                    if entsize == 24:
                        (st_name, st_info, st_other, st_shndx,
                         st_value, st_size) = struct.unpack(
                            endian + "IBBHQQ", entry
                        )
                    else:
                        continue
                    if st_value == 0 or st_shndx == 0:
                        continue
                    name = _read_cstr(strtab, st_name)
                    if name:
                        syms[name] = st_value
            return syms

        # Try .symtab first (preferred, has all symbols)
        if symtab_info and strtab_info and symtab_info["entsize"]:
            nsyms = symtab_info["size"] // symtab_info["entsize"]
            symbols = _read_elf_symtab(
                strtab_info["offset"], strtab_info["size"],
                symtab_info["offset"], symtab_info["entsize"], nsyms,
            )

        # Fall back to .dynsym
        if not symbols and dynsym_info and dynstr_info and dynsym_info["entsize"]:
            nsyms = dynsym_info["size"] // dynsym_info["entsize"]
            symbols = _read_elf_symtab(
                dynstr_info["offset"], dynstr_info["size"],
                dynsym_info["offset"], dynsym_info["entsize"], nsyms,
            )

        return symbols


# ---------------------------------------------------------------------------
#  PE/COFF symbol table reader (Windows)
# ---------------------------------------------------------------------------


def _read_pe_syms(path: str) -> dict[str, int]:
    """Parse PE export address table from a .dll file.

    Windows dlls typically export only a small set of public symbols.
    _bist_* functions may be internal (not exported). We try:
    1. COFF symbol table (if present)
    2. Export directory table (for exported symbols)

    Returns dict {sym_name: RVA (relative virtual address)}.
    """
    with open(path, "rb") as f:
        dos = f.read(64)
        e_lfanew = struct.unpack("<I", dos[60:64])[0]

        f.seek(e_lfanew)
        sig = f.read(4)
        if sig != b"PE\x00\x00":
            raise ValueError("Not a PE file")

        coff = f.read(20)
        (machine, number_of_sections, time_date_stamp,
         pointer_to_symbol_table, number_of_symbols,
         size_of_optional_header, characteristics) = struct.unpack(
            "<HHIIIHH", coff
        )

        symbols = {}

        # Pass 1: COFF symbol table
        if pointer_to_symbol_table and number_of_symbols:
            f.seek(pointer_to_symbol_table)
            for _ in range(number_of_symbols):
                entry = f.read(18)
                if len(entry) < 18:
                    break
                name_bytes = entry[:8]
                value = struct.unpack("<I", entry[8:12])[0]
                section_num = struct.unpack("<H", entry[12:14])[0]
                storage_class = entry[16]

                if storage_class == 2:  # IMAGE_SYM_CLASS_EXTERNAL
                    if name_bytes[0:1] == b"/":
                        # Long name in string table
                        off_str = name_bytes[1:].split(b"\x00")[0]
                        try:
                            off = int(off_str)
                        except ValueError:
                            continue
                        cur = f.tell()
                        f.seek(pointer_to_symbol_table + number_of_symbols * 18 + off)
                        name = _read_pe_str(f)
                        f.seek(cur)
                    else:
                        name = name_bytes.split(b"\x00")[0].decode("ascii", errors="replace")

                    if name and value:
                        symbols[name] = value

        # Pass 2: Export directory table
        opt_start = e_lfanew + 24
        f.seek(opt_start)
        opt_magic = struct.unpack("<H", f.read(2))[0]

        if opt_magic == 0x20B:  # PE32+
            f.seek(opt_start + 108)
        elif opt_magic == 0x10B:  # PE32
            f.seek(opt_start + 96)
        else:
            return symbols

        export_rva, export_size = struct.unpack("<II", f.read(8))

        if not export_rva or not export_size:
            return symbols

        # Get section headers for RVA→file offset conversion
        f.seek(e_lfanew + 24 + size_of_optional_header)
        sections = []
        for i in range(number_of_sections):
            shdr = f.read(40)
            if len(shdr) < 40:
                break
            sec_name = shdr[:8].rstrip(b"\x00").decode("ascii", errors="replace") or f".s{i}"
            sec_vsize = struct.unpack("<I", shdr[8:12])[0]
            sec_vaddr = struct.unpack("<I", shdr[12:16])[0]
            sec_ptr_raw = struct.unpack("<I", shdr[20:24])[0]
            sections.append({
                "name": sec_name, "vaddr": sec_vaddr,
                "vsize": sec_vsize, "ptr_raw": sec_ptr_raw,
            })

        def rva_to_offset(rva):
            for s in sections:
                if s["vaddr"] <= rva < s["vaddr"] + s["vsize"]:
                    return s["ptr_raw"] + (rva - s["vaddr"])
            return rva

        # Parse export directory
        export_off = rva_to_offset(export_rva)
        f.seek(export_off)
        hdr_data = f.read(40)
        if len(hdr_data) < 40:
            return symbols

        (exp_flags, exp_timestamp, exp_major, exp_minor,
         exp_name_rva, exp_ordinal_base,
         exp_num_functions, exp_num_names,
         exp_addr_tbl_rva, exp_name_tbl_rva,
         exp_ord_tbl_rva) = struct.unpack("<IIIIIHHIIII", hdr_data)

        addr_tbl_off = rva_to_offset(exp_addr_tbl_rva)
        name_tbl_off = rva_to_offset(exp_name_tbl_rva)

        for i in range(min(exp_num_names, 65536)):
            f.seek(name_tbl_off + i * 4)
            name_rva = struct.unpack("<I", f.read(4))[0]
            name_off = rva_to_offset(name_rva)
            name = _read_pe_str_at_offset(f, name_off)

            f.seek(exp_ord_tbl_rva + i * 2)
            ord_val = struct.unpack("<H", f.read(2))[0]

            f.seek(addr_tbl_off + ord_val * 4)
            addr_rva = struct.unpack("<I", f.read(4))[0]

            if name and addr_rva:
                symbols[name] = addr_rva

        return symbols


def _read_pe_str(f) -> str:
    """Read a null-terminated string from current file position."""
    buf = b""
    while True:
        c = f.read(1)
        if not c or c == b"\x00":
            break
        buf += c
    return buf.decode("utf-8", errors="replace")


def _read_pe_str_at_offset(f, offset: int) -> str:
    """Read a null-terminated string at a specific file offset."""
    cur = f.tell()
    f.seek(offset)
    s = _read_pe_str(f)
    f.seek(cur)
    return s


# ---------------------------------------------------------------------------
#  Format detection
# ---------------------------------------------------------------------------


def _detect_format(path: str) -> str:
    """Detect binary format by magic bytes."""
    with open(path, "rb") as f:
        magic = f.read(4)
    # ELF
    if magic[:4] == b"\x7fELF":
        return "elf"
    # PE (MZ)
    if magic[:2] == b"MZ":
        return "pe"
    # Mach-O thin: MH_MAGIC_64 = 0xFEEDFACF, MH_CIGAM_64 = 0xCFFEEDFE
    if magic in (b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe"):
        return "macho"
    le_val = struct.unpack("<I", magic)[0]
    if le_val in (0xFEEDFACF, 0xCFFEEDFE, 0xBEBAFECA):
        return "macho"
    # Mach-O fat: FAT_MAGIC = 0xCAFEBABE (stored as BE = \xca\xfe\xba\xbe)
    if magic == b"\xca\xfe\xba\xbe":
        return "macho"
    return "unknown"


# ---------------------------------------------------------------------------
#  Generic API
# ---------------------------------------------------------------------------


def discover_symbols(path: str) -> dict[str, int]:
    """Discover all executable symbols in a Stata shared library.

    Returns dict {sym_name: vmaddr}.
    """
    fmt = _detect_format(path)
    if fmt == "macho":
        return _read_macho_syms(path)
    elif fmt == "elf":
        return _read_elf_syms(path)
    elif fmt == "pe":
        return _read_pe_syms(path)
    else:
        raise ValueError(f"Unknown binary format: {fmt}")


def filter_bist_symbols(symbols: dict) -> dict[str, int]:
    """Filter symbol dict to retain all needed symbols for _engine.py.

    Includes:
    - _bist_*
    - _bi_st_*
    - _StataSO_*
    - _stpy_* (reference markers, these need embedded Python)
    - Private internal functions used by the engine for scalar/matrix ops

    Returns filtered dict.
    """
    # Known private internal functions used in _engine.py / _core.py.
    # These are non-external ("was a private external") symbols found via
    # nm -m on the dylib.  Not all exist in every Stata version; the
    # auto-generation only includes those that are actually present.
    _EXTRA_SYMS: set[str] = {
        # Push/stack helpers (standard ARM64 ABI)
        "_pushint", "_pushdbl", "_pushstr", "_pushflt",
        # Matrix type support
        "_m_mktsmatsto",
        # Scalar set operations (standard ARM64 ABI, not internal stack)
        "_stscalsave",           # call_set_scalar()
        "_xgso_newcp_fast_code", # call_set_strscalar() — create GSO from string
        "_put_xgso_scalar",      # call_set_strscalar() — put GSO as scalar
    }
    filtered = {}
    for name, addr in symbols.items():
        if name.startswith("_bist_") or name.startswith("_bi_st_") or \
           name.startswith("_StataSO_") or name.startswith("_stpy_") or \
           name in _EXTRA_SYMS:
            filtered[name] = addr
    return filtered


def _find_macho_text_slice(raw_bytes: bytes) -> Optional[tuple[bytes, int]]:
    """Extract the thin Mach-O arm64 slice from a (possibly fat) binary.

    Returns (thin_bytes, slice_offset_in_file) or None if not found.
    slice_offset_in_file is the file offset of the thin Mach-O start.
    """
    if len(raw_bytes) < 4:
        return None
    fat_magic_le = struct.unpack("<I", raw_bytes[:4])[0]
    is_fat = fat_magic_le == FAT_CIGAM or raw_bytes[:4] == b"\xca\xfe\xba\xbe"

    slice_start = 0
    if is_fat:
        # FAT_MAGIC is big-endian
        fat_endian = ">"
        narch = struct.unpack(fat_endian + "I", raw_bytes[4:8])[0]
        target_cputype = _current_macho_cputype()
        for i in range(narch):
            entry_off = 8 + i * 20
            cputype = struct.unpack(fat_endian + "I", raw_bytes[entry_off:entry_off + 4])[0]
            if cputype == target_cputype:
                slice_start = struct.unpack(fat_endian + "I", raw_bytes[entry_off + 8:entry_off + 12])[0]
                break
        if slice_start == 0:
            return None
        thin_bytes = raw_bytes[slice_start:]
    else:
        thin_bytes = raw_bytes
    return thin_bytes, slice_start


def _macho_vmaddr_to_fileoff(thin_bytes: bytes, vmaddr: int) -> Optional[int]:
    """Convert a vmaddr to file offset in a thin Mach-O binary."""
    if len(thin_bytes) < 32:
        return None
    ncmds = struct.unpack_from("<I", thin_bytes, 16)[0]
    offset = 32  # after mach_header_64
    for _ in range(ncmds):
        if offset + 8 > len(thin_bytes):
            return None
        cmd, cmdsz = struct.unpack_from("<II", thin_bytes, offset)
        if cmd == 0x19:  # LC_SEGMENT_64
            segname = thin_bytes[offset + 8:offset + 24].decode().rstrip("\x00")
            vmaddr_seg = struct.unpack_from("<Q", thin_bytes, offset + 24)[0]
            fileoff_seg = struct.unpack_from("<Q", thin_bytes, offset + 40)[0]
            vmsize = struct.unpack_from("<Q", thin_bytes, offset + 32)[0]
            if vmaddr_seg <= vmaddr < vmaddr_seg + vmsize:
                return vmaddr - vmaddr_seg + fileoff_seg
        offset += cmdsz
    return None


def discover_data_offsets(path: str) -> Optional[dict]:
    """Discover STACK_PTR_OFFSET and ERR_ADDR_RELATIVE from ARM64 binary disassembly.

    Uses capstone to disassemble _pushdbl and _st_store_u, extracting
    the runtime data page base and field offsets from adrp+add pairs.

    Returns dict with "stack_ptr_delta" and "err_addr_delta" (int, delta from _BASE),
    or None for non-ARM64 binaries or if discovery fails.
    """
    import capstone as cs

    all_syms = discover_symbols(path)
    if "_pushdbl" not in all_syms or "_st_store_u" not in all_syms:
        return None  # Not ARM64 or missing required symbols

    with open(path, "rb") as f:
        raw = f.read()

    result = _find_macho_text_slice(raw)
    if result is None:
        return None  # Not a Mach-O binary
    thin_bytes, slice_offset = result

    # Known data page base (confirmed: shared between _pushdbl and _st_store_u)
    adrp_page: Optional[int] = None
    stack_ptr_delta: Optional[int] = None
    err_addr_delta: Optional[int] = None

    md = cs.Cs(cs.CS_ARCH_ARM64, cs.CS_MODE_ARM)

    # Need to track: for each function, find adrp+add pairs that reference
    # the runtime data page and record the computed delta (page + field offset).
    # Both _pushdbl and _st_store_u use the same page base.
    for fn_name in ("_pushdbl", "_st_store_u"):
        vm = all_syms.get(fn_name)
        if vm is None:
            continue
        foff = _macho_vmaddr_to_fileoff(thin_bytes, vm)
        if foff is None:
            continue
        fn_bytes = raw[slice_offset + foff:slice_offset + foff + 256]

        # Track adrp targets: {register_name: page}
        adrp_regs: dict[str, int] = {}
        for insn in md.disasm(fn_bytes, vm):
            if insn.mnemonic == "adrp":
                # Parse: "adrp x8, #0x39b7000"
                parts = insn.op_str.split(",")
                if len(parts) >= 2:
                    reg = parts[0].strip()
                    target_str = parts[1].strip()
                    if target_str.startswith("#0x"):
                        page = int(target_str[1:], 16)
                    elif target_str.startswith("#"):
                        page = int(target_str[1:])
                    else:
                        continue
                    adrp_regs[reg] = page

            if insn.mnemonic == "add" and insn.op_str.count(",") >= 2:
                parts = insn.op_str.split(",")
                dst_reg = parts[0].strip()
                src_reg = parts[1].strip()
                imm_part = parts[2].strip()
                if dst_reg in adrp_regs and src_reg == dst_reg:
                    if imm_part.startswith("#0x"):
                        imm_val = int(imm_part[1:], 16)
                    elif imm_part.startswith("#"):
                        imm_val = int(imm_part[1:])
                    else:
                        continue
                    page = adrp_regs[dst_reg]
                    delta = page + imm_val

                    # Classify by the offset value
                    if imm_val == 0x108:
                        stack_ptr_delta = delta
                        adrp_page = page
                    elif imm_val == 0x11c:
                        err_addr_delta = delta
                        adrp_page = page

    # Validate: both offsets must be found and share the same page base
    if adrp_page is not None and stack_ptr_delta is not None and err_addr_delta is not None:
        return {
            "stack_ptr_delta": stack_ptr_delta,
            "err_addr_delta": err_addr_delta,
        }

    # Fallback: if we found the page but only one offset, try to compute the other
    if adrp_page is not None and stack_ptr_delta is not None and err_addr_delta is None:
        # Error field is at page + 0x11c (20 bytes after stack pointer field at +0x108)
        # This is a documented struct-field relationship within the runtime data area.
        err_addr_delta = adrp_page + 0x11c
        return {
            "stack_ptr_delta": stack_ptr_delta,
            "err_addr_delta": err_addr_delta,
        }

    return None


def build_manifest(path: str, output_path: Optional[str] = None,
                   include_dynstr: bool = False) -> dict:
    """Build a complete manifest for a Stata shared library.

    Args:
        path: Path to .dylib/.so/.dll
        output_path: If provided, write manifest JSON to this path
        include_dynstr: If True, include metadata from dynamic section

    Returns:
        Manifest dict with sha256, file_size, format, symbols, etc.
    """
    fhash = file_sha256(path)
    stat = os.stat(path)
    fmt = _detect_format(path)
    all_syms = discover_symbols(path)
    bist_syms = filter_bist_symbols(all_syms)
    data_offsets = discover_data_offsets(path)

    manifest = {
        "sha256": fhash,
        "file_size": stat.st_size,
        "format": fmt,
        "platform": sys.platform,
        "n_total_symbols": len(all_syms),
        "n_bist_symbols": len(bist_syms),
        "symbols": bist_syms,
        "data_offsets": data_offsets,  # None for x86_64
    }

    if fmt == "macho":
        _add_macho_metadata(path, manifest)
    elif fmt == "elf":
        _add_elf_metadata(path, manifest)

    if output_path:
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(manifest, f, indent=2)

    return manifest


def _add_macho_metadata(path: str, manifest: dict) -> None:
    """Add Mach-O metadata like dylib version to manifest."""
    with open(path, "rb") as f:
        magic_raw = f.read(4)
    magic_le = struct.unpack("<I", magic_raw)[0]

    # Fat header is always big-endian
    fat_endian = None
    if magic_le == FAT_CIGAM or struct.unpack(">I", magic_raw)[0] == FAT_MAGIC:
        fat_endian = ">"

    offset = 0
    if fat_endian is not None:
        with open(path, "rb") as f:
            f.read(4)
            narch = struct.unpack(fat_endian + "I", f.read(4))[0]
            target_cputype = _current_macho_cputype()
            for i in range(narch):
                cputype = struct.unpack(fat_endian + "I", f.read(4))[0]
                f.read(4)
                off = struct.unpack(fat_endian + "I", f.read(4))[0]
                sz = struct.unpack(fat_endian + "I", f.read(4))[0]
                f.read(4)
                if (cputype & 0x00FFFFFF) == (target_cputype & 0x00FFFFFF):
                    offset = off
                    break

    with open(path, "rb") as f:
        f.seek(offset + 4)
        magic = struct.unpack("<I", f.read(4))[0]
        endian = ">" if magic == MH_CIGAM_64 else "<"

        f.seek(offset + 4 + 4 + 4)  # cputype + cpusubtype
        ncmds = struct.unpack(endian + "I", f.read(4))[0]
        f.read(4 + 4)  # sizeofcmds + flags + reserved

        for _ in range(ncmds):
            cmd_start = f.tell()
            lc_cmd, lc_cmdsize = struct.unpack(endian + "II", f.read(8))

            if lc_cmd == 0x2D:  # LC_ID_DYLIB
                data = f.read(lc_cmdsize - 8)
                if len(data) >= 28:
                    ver = struct.unpack(endian + "III", data[16:28])
                    manifest["dylib_version"] = f"{ver[0]}.{ver[1]}.{ver[2]}"
                break
            f.seek(cmd_start + lc_cmdsize)


def _add_elf_metadata(path: str, manifest: dict) -> None:
    """Add ELF metadata like SONAME to manifest."""
    with open(path, "rb") as f:
        ident = f.read(16)
        endian = "<" if ident[5] == 1 else ">"
        f.seek(0)
        ehdr = f.read(64)
        (e_ident, e_type, e_machine, e_version, e_entry,
         e_phoff, e_shoff, e_flags, e_ehsize, e_phentsize,
         e_phnum, e_shentsize, e_shnum, e_shstrndx) = struct.unpack(
            endian + "16sHHIIQQQIHHHH", ehdr
        )

        f.seek(e_shoff + e_shstrndx * e_shentsize)
        shstr_ent = f.read(e_shentsize)
        (sh_name, sh_type, sh_flags, sh_addr, sh_offset,
         sh_size, sh_link, sh_info, sh_addralign, sh_entsize) = \
            struct.unpack(endian + "IIQQQQIIQQ", shstr_ent)
        f.seek(sh_offset)
        shstrtab = f.read(sh_size)

        strtab_info = None
        for i in range(e_shnum):
            f.seek(e_shoff + i * e_shentsize)
            shdr = f.read(e_shentsize)
            (sh_name, sh_type, sh_flags, sh_addr, sh_offset_v,
             sh_size, sh_link, sh_info, sh_addralign, sh_entsize) = \
                struct.unpack(endian + "IIQQQQIIQQ", shdr)
            name = _read_cstr(shstrtab, sh_name)
            if name == ".strtab":
                strtab_info = {"offset": sh_offset_v, "size": sh_size}
            elif name == ".dynamic":
                # Read DT_SONAME
                f.seek(sh_offset_v)
                soname_off = 0
                strtab_base = 0
                for j in range(sh_size // 16):
                    entry = f.read(16)
                    if len(entry) < 16:
                        break
                    d_tag, d_val = struct.unpack(endian + "QQ", entry)
                    if d_tag == 14:  # DT_SONAME
                        soname_off = d_val
                    elif d_tag == 10:  # DT_STRTAB
                        strtab_base = d_val
                if soname_off and strtab_base and strtab_info:
                    rel_off = soname_off - strtab_base
                    f.seek(strtab_info["offset"] + rel_off)
                    manifest["soname"] = _read_cstr(f.read(128), 0)
                break


# ---------------------------------------------------------------------------
#  CLI entry point
# ---------------------------------------------------------------------------


def main():
    """CLI: python -m pystata_x.sfi._manifest <path-to-lib>"""
    import argparse
    parser = argparse.ArgumentParser(
        description="Build manifest for a Stata shared library"
    )
    parser.add_argument("path", help="Path to libstata-{edition}.{dylib,so,dll}")
    parser.add_argument("-o", "--output", help="Output path for manifest.json")
    parser.add_argument(
        "--filter", action="store_true", default=True,
        help="Filter to only _bist_* and related symbols",
    )
    parser.add_argument(
        "--all", dest="filter", action="store_false",
        help="Include all symbols",
    )
    args = parser.parse_args()

    manifest = build_manifest(args.path, output_path=args.output)
    sha = manifest["sha256"][:16] + "..." + manifest["sha256"][-16:]
    print(f"File:       {args.path}")
    print(f"SHA256:     {sha}")
    print(f"Size:       {manifest['file_size']:,} bytes")
    print(f"Format:     {manifest.get('format', '?')}")
    print(f"Total syms: {manifest['n_total_symbols']}")
    print(f"Bist syms:  {manifest['n_bist_symbols']}")
    if "dylib_version" in manifest:
        print(f"Version:    dylib {manifest['dylib_version']}")
    if "soname" in manifest:
        print(f"SONAME:     {manifest['soname']}")


if __name__ == "__main__":
    main()
