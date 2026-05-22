"""Windows PE StataBinary — extend pystata-analyzer for PE binaries."""
import ctypes
import hashlib
import json
import struct
import os
from pathlib import Path
from typing import Optional


class PEConvert:
    """Convert file offsets to PE virtual addresses and vice versa."""

    def __init__(self, data: bytes):
        self.data = data
        self._parse_headers()

    def _parse_headers(self):
        d = self.data
        self.e_lfanew = struct.unpack('<I', d[0x3c:0x40])[0]
        pe = d[self.e_lfanew:self.e_lfanew+0x200]
        self.num_sections = struct.unpack('<H', pe[6:8])[0]
        self.opt_hdr_size = struct.unpack('<H', pe[20:22])[0]
        self.section_hdr_off = self.e_lfanew + 24 + self.opt_hdr_size

        self.sections = []
        for i in range(self.num_sections):
            sh = d[self.section_hdr_off + i*40 : self.section_hdr_off + i*40 + 40]
            name = sh[:8].rstrip(b'\x00').decode('utf-8', errors='replace')
            vs = struct.unpack('<I', sh[8:12])[0]
            va = struct.unpack('<I', sh[12:16])[0]
            rs = struct.unpack('<I', sh[16:20])[0]
            ro = struct.unpack('<I', sh[20:24])[0]
            self.sections.append({
                'name': name, 'va': va, 'vsize': vs,
                'raw_offset': ro, 'raw_size': rs
            })

    def rva_to_offset(self, rva):
        for sec in self.sections:
            end = sec['va'] + sec['raw_size']
            if sec['va'] <= rva < end:
                return rva - sec['va'] + sec['raw_offset']
        return None

    def offset_to_rva(self, offset):
        for sec in self.sections:
            end = sec['raw_offset'] + sec['raw_size']
            if sec['raw_offset'] <= offset < end:
                return offset - sec['raw_offset'] + sec['va']
        return None


class PEStata:
    """Analyze se-64.dll (Windows PE Stata binary).

    Discovers: dispatch table, push functions, data offsets, memory layout.
    """

    def __init__(self, dll_path: str):
        self.path = dll_path
        with open(dll_path, 'rb') as f:
            self.data = f.read()
        self.pe = PEConvert(self.data)
        self.text_data = None
        self._loaded = False

    @property
    def sha256(self) -> str:
        h = hashlib.sha256()
        h.update(self.data)
        return h.hexdigest()

    def analyze(self):
        """Run full analysis pipeline."""
        self._text_section = None
        self._data_section = None
        for sec in self.pe.sections:
            if sec['name'] == '.text':
                off = sec['raw_offset']
                sz = sec['raw_size']
                self.text_data = self.data[off:off+sz]
                self._text_section = sec
            elif sec['name'] == '.data':
                self._data_section = sec

        self._discover_dispatcher()
        self._discover_thin_wrappers()
        self._loaded = True

    # ── Dispatcher discovery ──
    def _discover_dispatcher(self):
        """Find the bytecode interpreter (main dispatcher)."""
        d = self.text_data
        text_rva = self._text_section['va']
        call_counts = {}
        for i in range(len(d) - 9):
            if d[i] == 0xb8 and d[i+5] == 0xe8:
                rel = struct.unpack('<i', d[i+6:i+10])[0]
                target = text_rva + i + 10 + rel
                call_counts[target] = call_counts.get(target, 0) + 1
        self.call_counts = call_counts
        if call_counts:
            self.main_dispatcher = max(call_counts, key=call_counts.get)
            self.dispatcher_count = call_counts[self.main_dispatcher]
        else:
            self.main_dispatcher = None
            self.dispatcher_count = 0

    def _discover_thin_wrappers(self):
        """Find dispatch thin wrappers (mov eax, <id>; call dispatcher; ret)."""
        d = self.text_data
        text_rva = self._text_section['va']
        wrappers = []
        for i in range(len(d) - 9):
            if d[i] == 0xb8:  # mov eax, imm32
                const = struct.unpack('<I', d[i+1:i+5])[0]
                if d[i+5] == 0xe8:  # call rel32
                    rel = struct.unpack('<i', d[i+6:i+10])[0]
                    target = text_rva + i + 10 + rel
                    if target == self.main_dispatcher:
                        # Check for ret within 30 bytes
                        for j in range(i+10, min(i+30, len(d))):
                            if d[j] == 0xc3:
                                wrappers.append({
                                    'rva': text_rva + i,
                                    'dispatch_id': const,
                                    'size': j - i + 1
                                })
                                break
                            if j > i+15 and d[j] in (0x48, 0x8b, 0x89):
                                break
        self.thin_wrappers = wrappers
        self.dispatch_ids = sorted(set(w['dispatch_id'] for w in wrappers))

    # ── Memory discovery via DLL loading ──
    def discover_memory_offsets(self, dll_handle: int):
        """Discover memory offsets by loading DLL and scanning for known values.

        Args:
            dll_handle: The handle (base address) of the loaded se-64.dll
        """
        self.base = dll_handle
        data_ptr = dll_handle + self._data_section['va']
        data_size = self._data_section['vsize']

        # Read .data section from loaded DLL
        buf = (ctypes.c_char * data_size)()
        ctypes.memmove(buf, ctypes.c_void_p(data_ptr), data_size)
        self._mem_data = buf.raw

        return {
            'data_base_rva': self._data_section['va'],
            'data_size': data_size,
        }

    def scan_nvar_nobs(self, known_nvar: int = 12, known_nobs: int = 74):
        """Scan .data section for nvar/nobs after loading a known dataset.

        Returns candidates that match (nvar, nobs) values.
        """
        # Already scanned with dataset loaded — now change dataset
        # and re-scan to find which values change
        pass  # call this after changing dataset externally

    # ── Manifest generation ──
    def generate_manifest(self, dll_handle: int = 0,
                          extra: dict = None) -> dict:
        """Generate a Windows-specific manifest.

        Returns dict matching the v3 manifest format.
        """
        manifest = {
            'format_version': 3,
            'platform': 'windows-x86_64',
            'sha256': self.sha256,
            'analysis_date': __import__('datetime').datetime.now().isoformat(),
            'binary': {
                'path': os.path.basename(self.path),
                'size': len(self.data),
                'sha256': self.sha256,
            },
            'dispatch_table': {
                'main_dispatcher_rva': self.main_dispatcher,
                'num_callers': self.dispatcher_count,
                'num_thin_wrappers': len(self.thin_wrappers),
                'dispatch_ids': self.dispatch_ids,
            },
            'memory_discovery': {},
        }
        if dll_handle:
            offsets = self.discover_memory_offsets(dll_handle)
            manifest['memory_offsets'] = offsets

        if extra:
            manifest.update(extra)
        return manifest
