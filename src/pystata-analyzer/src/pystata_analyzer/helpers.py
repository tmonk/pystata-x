"""Shared constants, helpers, and Capstone availability check."""

import struct
from typing import Optional

# ── Capstone (optional — install for disassembly output) ─────────────────
try:
    from capstone import Cs as _Cs, CS_ARCH_X86, CS_MODE_64
    HAS_CAPSTONE = True
except ImportError:
    _Cs = None  # type: ignore
    CS_ARCH_X86 = CS_MODE_64 = None
    HAS_CAPSTONE = False

CURRENT_MANIFEST_VERSION = 2

# ── Known x86_64 global addresses ────────────────────────────────────────
ARG_PTR_ADDR = 0x500C6A0     # .bss: push functions update, _save_sp reads
SP_GLOBAL_ADDR = 0x500C638   # .bss: checker sets, SP-resetting thunks write
ERROR_ADDR = 0x500C698        # .bss: Stata's internal error code global


def _cstr(buf: bytes, start: int) -> str:
    """Read a null-terminated ASCII string from *buf* at *start*."""
    end = buf.find(b"\0", start)
    if end < 0:
        return buf[start:].decode("ascii", errors="replace")
    return buf[start:end].decode("ascii", errors="replace")


def _find_bytes(haystack: bytes, needle: bytes) -> list[int]:
    """Return all indices where *needle* appears in *haystack*."""
    pos = 0
    hits = []
    while True:
        idx = haystack.find(needle, pos)
        if idx < 0:
            break
        hits.append(idx)
        pos = idx + 1
    return hits


def _is_float(s: str) -> bool:
    """Return True if *s* could be a float literal."""
    try:
        float(s)
        return True
    except ValueError:
        return False


def _fn_start(raw: bytes, start_off: int, base_vaddr: int,
              search_back: int = 200) -> Optional[int]:
    """Find the start of a function by searching backward for a prologue.

    Looks for ``sub rsp, N`` (``48 83 ec NN``) first, then ``push rbp``
    (``0x55``) as fallback.

    Returns the absolute virtual address, or None if not found.
    """
    search_from = max(0, start_off - search_back)
    chunk = raw[search_from:start_off]
    # Prefer: sub rsp, <imm8>  (48 83 ec NN)
    needle = bytes([0x48, 0x83, 0xec])
    candidates = _find_bytes(chunk, needle)
    if candidates:
        best_off = max(candidates)  # closest to target
        return base_vaddr + search_from + best_off
    # Fallback: push rbp (0x55)
    for offset in range(len(chunk) - 1, -1, -1):
        if chunk[offset] == 0x55:
            # Verify it's a function start by checking previous byte
            if offset == 0 or chunk[offset - 1] not in (0x55, 0xcc, 0x90, 0xc3):
                return base_vaddr + search_from + offset
    return None


def _fn_size(raw: bytes, vaddr: int, base_vaddr: int,
             max_size: int = 65536) -> int:
    """Estimate function size by scanning for a ``ret`` at depth 0."""
    start_off = vaddr - base_vaddr
    if start_off < 0 or start_off >= len(raw):
        return 0
    chunk = raw[start_off:start_off + max_size]
    # Look for ret (0xc3) at the end of a basic block
    for i, b in enumerate(chunk):
        if b == 0xc3 and i > 4:
            # Verify this is a real function end by checking if
            # there's actual code before it
            return i + 1
    return min(max_size, len(chunk))
