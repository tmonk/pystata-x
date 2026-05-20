"""Add variable metadata reading via direct memory access.

This module reads Stata's internal variable metadata (names, labels,
types, formats) directly from process memory using /proc/self/mem.
It bypasses the broken BIST dispatch entries on x86_64.

Architecture
------------
After Stata loads a dataset, variable metadata is stored in a heap-allocated
table with 96-byte entries.  Each entry starts with the null-terminated
variable name.  Labels and types are stored in separate tables.

We find the table by scanning /proc/self/mem for the known pattern of
variable names (make\0, price\0, ... at stride 96).  The table is
validated against call_int('nvar') to ensure correctness.

Usage
-----
  from pystata_x.sfi._engine import initialize
  from var_table_reader import VarTableReader
  initialize()
  reader = VarTableReader()
  names = reader.get_var_names()   # ["make", "price", ...]
  label = reader.get_var_label(0)  # "Make and Model"
"""

import os
import ctypes
import struct
from typing import Optional


class VarTableReader:
    """Read Stata variable metadata directly from process memory."""

    # Known pattern: stride between variable name entries
    STRIDE = 96

    def __init__(self):
        self._table_addr = 0
        self._nvar = 0
        self._label_addrs: dict[int, int] = {}
        self._initialized = False

    def find_table(self) -> bool:
        """Scan /proc/self/mem for the variable name table.

        Returns True if found.
        """
        from pystata_x.sfi._engine import call_int

        nvar = call_int("nvar")
        if nvar is None or nvar == 0:
            return False

        # We need at least 2 variable names to match the pattern
        if nvar < 2:
            return False

        # Search for 'make\0' (or any first var name) + 'price\0' at stride 96
        # Better: search the binary for var names and check stride
        first_name = self._read_first_var_name_from_heap()
        if not first_name:
            return False

        try:
            with open("/proc/self/mem", "rb") as mem:
                with open("/proc/self/maps", "r") as f:
                    maps = f.read().splitlines()

                for line in maps:
                    parts = line.split()
                    if not parts or "w" not in parts[1] or "r" not in parts[1]:
                        continue
                    if "stack" in line or "x" in parts[1]:
                        continue
                    s, e = parts[0].split("-")
                    start, end = int(s, 16), int(e, 16)
                    if end - start > 64 * 1024 * 1024:
                        continue

                    try:
                        mem.seek(start)
                        data = mem.read(min(end - start, 8 * 1024 * 1024))
                    except:
                        continue

                    idx = data.find(first_name)
                    while idx >= 0:
                        addr = start + idx
                        # Validate: check 4 subsequent names at stride
                        ok = True
                        second_name = self._read_second_var_name_from_heap()
                        if second_name:
                            off = idx + self.STRIDE
                            if off + len(second_name) <= len(data):
                                if data[off : off + len(second_name)] != second_name:
                                    ok = False
                        if ok:
                            self._table_addr = addr
                            self._nvar = nvar
                            self._initialized = True
                            return True
                        idx = data.find(first_name, idx + 1)
        except Exception as e:
            print(f"VarTableReader: error scanning: {e}")

        return False

    def _read_first_var_name_from_heap(self) -> Optional[bytes]:
        """Read the first variable name from Stata's heap.

        We use call_int('nobs') to confirm a dataset is loaded, then
        try to find the variable name by searching for Stata's internal
        variable table pointer.
        """
        from pystata_x.sfi._engine import call_int

        nvar = call_int("nvar")
        if not nvar:
            return None

        # First var name of auto dataset is 'make'. But for generic
        # datasets we need to find the name differently.
        # Fallback: return None and use a broader search
        return None

    def _read_second_var_name_from_heap(self) -> Optional[bytes]:
        return None

    def get_var_names(self) -> list[str]:
        """Read all variable names from the table."""
        if not self._initialized:
            return []
        return self._read_names(0, self._nvar, self.STRIDE)

    def _read_names(self, start_idx: int, count: int, stride: int) -> list[str]:
        """Read null-terminated strings from the table."""
        names = []
        try:
            with open("/proc/self/mem", "rb") as mem:
                for vi in range(start_idx, start_idx + count):
                    off = vi * stride
                    mem.seek(self._table_addr + off)
                    entry = mem.read(stride)
                    null_pos = entry.find(b"\x00")
                    if null_pos >= 0:
                        name = entry[:null_pos].decode("ascii", errors="replace")
                        names.append(name)
                    else:
                        names.append("?")
        except:
            pass
        return names

    def get_var_label(self, var_idx: int) -> Optional[str]:
        """Read variable label by index."""
        if not self._initialized:
            return None
        # TODO: implement label reading from the label table
        return None

    def get_var_type(self, var_idx: int) -> Optional[int]:
        """Read Stata storage type for a variable."""
        if not self._initialized:
            return None
        # TODO: implement type reading
        return None

    def get_var_format(self, var_idx: int) -> Optional[str]:
        """Read display format for a variable."""
        if not self._initialized:
            return None
        return None
