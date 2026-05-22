"""Run PEStata analysis on se-64.dll and generate Windows manifest."""
import ctypes
import json
import struct
import sys

sys.path.insert(0, 'C:\\Users\\tom\\projects\\pystata-x\\src\\pystata-analyzer\\src')
from pystata_analyzer.pe_binary import PEStata

print('Loading PEStata...', flush=True)
pe = PEStata(r'C:\Program Files\StataNow19\se-64.dll')
print('DLL loaded: %d bytes' % len(pe.data), flush=True)

print('Analyzing...', flush=True)
pe.analyze()

print('Main dispatcher RVA: %s' % hex(pe.main_dispatcher), flush=True)
print('Dispatcher callers: %d' % pe.dispatcher_count, flush=True)
print('Thin wrappers: %d' % len(pe.thin_wrappers), flush=True)
print('Unique dispatch IDs: %d' % len(pe.dispatch_ids), flush=True)

ids = sorted(pe.dispatch_ids)
print('Dispatch ID range: %d - %d' % (min(ids), max(ids)))
print('First 20 IDs: %s' % str(ids[:20]))

# Load DLL and init Stata
print('\nLoading DLL into memory...', flush=True)
dll = ctypes.WinDLL(r'C:\Program Files\StataNow19\se-64.dll')
handle = dll._handle

_Main = dll.StataSO_Main
_Main.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_char_p)]
_Main.restype = ctypes.c_int
_Main(2, (ctypes.c_char_p * 2)(b'stata', b'-q'))

_Execute = dll.StataSO_Execute
_Execute.argtypes = [ctypes.c_char_p]
_Execute.restype = ctypes.c_int

_Execute(b'sysuse auto, clear')
print('Loaded auto.dta (nvar=12, nobs=74)', flush=True)

# Discover memory offsets
offsets = pe.discover_memory_offsets(handle)
print('Data section: RVA=%s, size=%d' % (hex(offsets['data_base_rva']), offsets['data_size']), flush=True)

# Scan for nvar (12) and nobs (74)
raw = pe._mem_data
data_base = handle + pe._data_section['va']

found_nvar = []
found_nobs = []
for o in range(0, len(raw) - 8, 4):
    v32 = struct.unpack('<i', raw[o:o+4])[0]
    v64 = struct.unpack('<q', raw[o:o+8])[0]
    if v32 == 12:
        found_nvar.append((o, 32))
    elif v64 == 12:
        found_nvar.append((o, 64))
    if v32 == 74:
        found_nobs.append((o, 32))
    elif v64 == 74:
        found_nobs.append((o, 64))

print('nvar=12: %d candidates' % len(found_nvar), flush=True)
for off, sz in found_nvar[:10]:
    print('  offset=%s (%d-bit)' % (hex(off), sz), flush=True)

print('nobs=74: %d candidates' % len(found_nobs), flush=True)
for off, sz in found_nobs[:10]:
    print('  offset=%s (%d-bit)' % (hex(off), sz), flush=True)

# Change dataset and re-verify
_Execute(b'sysuse bpwide, clear')
print('\nLoaded bpwide.dta (nvar=5, nobs=36)', flush=True)

buf2 = (ctypes.c_char * offsets['data_size'])()
ctypes.memmove(buf2, ctypes.c_void_p(data_base), offsets['data_size'])
raw2 = buf2.raw

nvar_verified = []
for o, bs in found_nvar:
    if bs == 32 and o < len(raw2) - 4:
        if struct.unpack('<i', raw2[o:o+4])[0] == 5:
            nvar_verified.append((o, 32))
    elif bs == 64 and o < len(raw2) - 8:
        if struct.unpack('<q', raw2[o:o+8])[0] == 5:
            nvar_verified.append((o, 64))

print('nvar 12->5: %d verified' % len(nvar_verified), flush=True)
for o, bs in nvar_verified[:10]:
    print('  offset=%s (%d-bit)' % (hex(o), bs), flush=True)

nobs_verified = []
for o, bs in found_nobs:
    if bs == 32 and o < len(raw2) - 4:
        if struct.unpack('<i', raw2[o:o+4])[0] == 36:
            nobs_verified.append((o, 32))
    elif bs == 64 and o < len(raw2) - 8:
        if struct.unpack('<q', raw2[o:o+8])[0] == 36:
            nobs_verified.append((o, 64))

print('nobs 74->36: %d verified (by exact 74->36)' % len(nobs_verified), flush=True)
for o, bs in nobs_verified[:10]:
    print('  offset=%s (%d-bit)' % (hex(o), bs), flush=True)

# Additional nobs scan: try int8, int16, and float
print('\nExtended nobs scan (int16, int8, float32, float64):', flush=True)
# int16
for o in range(0, len(raw) - 2, 2):
    v16 = struct.unpack('<h', raw[o:o+2])[0]
    v16_2 = struct.unpack('<h', raw2[o:o+2])[0]
    if v16 == 74 and v16_2 == 36:
        print('  INT16: offset=%s' % hex(o), flush=True)
# int8
for o in range(0, len(raw) - 1, 1):
    v8 = raw[o]
    v8_2 = raw2[o]
    if v8 == 74 and v8_2 == 36:
        print('  INT8: offset=%s' % hex(o), flush=True)
# float32
for o in range(0, len(raw) - 4, 4):
    vf = struct.unpack('<f', raw[o:o+4])[0]
    vf2 = struct.unpack('<f', raw2[o:o+4])[0]
    if 73.9 < vf < 74.1 and 35.9 < vf2 < 36.1:
        print('  FLOAT32: offset=%s' % hex(o), flush=True)
# float64 (already covered above but let's verify)
for o in range(0, len(raw) - 8, 8):
    vd = struct.unpack('<d', raw[o:o+8])[0]
    vd2 = struct.unpack('<d', raw2[o:o+8])[0]
    if 73.9 < vd < 74.1 and 35.9 < vd2 < 36.1:
        print('  FLOAT64: offset=%s' % hex(o), flush=True)

# Maxvars
found_5000 = []
for o in range(0, len(raw) - 4, 4):
    if struct.unpack('<I', raw[o:o+4])[0] == 5000:
        found_5000.append(o)

print('maxvars=5000: %d candidates' % len(found_5000), flush=True)
for o in found_5000[:5]:
    print('  offset=%s' % hex(o), flush=True)

memory_layout = {}
if nvar_verified:
    memory_layout['nvar_offset'] = nvar_verified[0][0]
if nobs_verified:
    memory_layout['nobs_offset'] = nobs_verified[0][0]
if found_5000:
    memory_layout['maxvars_offset'] = found_5000[0]

manifest = pe.generate_manifest(handle, extra={
    'memory_offsets': memory_layout,
    'memory_discovery': {
        'data_base_rva': offsets['data_base_rva'],
        'data_size': offsets['data_size'],
        'candidates': {
            'nvar': [{'offset': o, 'bits': b} for o, b in nvar_verified],
            'nobs': [{'offset': o, 'bits': b} for o, b in nobs_verified],
            'maxvars': found_5000,
        }
    }
})

manifest_path = 'C:\\Users\\tom\\projects\\pystata-x\\src\\pystata_x\\sfi\\manifests\\manifest-windows-x86_64.json'
with open(manifest_path, 'w') as f:
    json.dump(manifest, f, indent=2)

print('\nManifest written to:', manifest_path, flush=True)
print('Memory offsets:', json.dumps(memory_layout, indent=2), flush=True)
print('Done', flush=True)
