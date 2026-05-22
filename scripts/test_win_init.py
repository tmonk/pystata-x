"""Debug manifest loading."""
import ctypes
import hashlib
import json
import os
import struct
import sys

sys.path.insert(0, r'C:\Users\tom\projects\pystata-x\src')
os.environ['STATA_LIB_PATH'] = r'C:\Program Files\StataNow19\se-64.dll'

# Compute SHA256 of the DLL
dll_path = r'C:\Program Files\StataNow19\se-64.dll'
h = hashlib.sha256()
with open(dll_path, 'rb') as f:
    while True:
        chunk = f.read(65536)
        if not chunk:
            break
        h.update(chunk)
fhash = h.hexdigest()
print('DLL SHA256:', fhash, flush=True)

# Check the manifest
manifest_path = r'C:\Users\tom\projects\pystata-x\src\pystata_x\sfi\manifests\manifest-windows-x86_64.json'
print('Manifest exists:', os.path.exists(manifest_path), flush=True)
if os.path.exists(manifest_path):
    with open(manifest_path) as f:
        mdata = json.load(f)
    print('Manifest SHA256:', mdata.get('sha256', ''), flush=True)
    print('SHA256 match:', fhash == mdata.get('sha256', ''), flush=True)
    print('Memory offsets in manifest:', mdata.get('memory_offsets', {}), flush=True)

# Now try to init and see what gets loaded
import pystata_x.sfi._engine as eng
print('\nBefore init:', flush=True)
print('  _MANIFEST sha:', eng._MANIFEST.get('sha256', '')[:16] if eng._MANIFEST else 'empty', flush=True)
print('  _MEMORY_OFFSETS:', eng._MEMORY_OFFSETS, flush=True)

eng.initialize()

print('\nAfter init:', flush=True)
print('  _INITIALIZED:', eng._INITIALIZED, flush=True)
print('  _MEMORY_OFFSETS:', eng._MEMORY_OFFSETS, flush=True)

# test var_count
from pystata_x.sfi._strategy import _STRATEGY
print('\nStrategy:', type(_STRATEGY).__name__, flush=True)
print('var_count:', _STRATEGY.var_count(), flush=True)

# test nvar directly from DLL handle
if eng._LIB is not None:
    handle = eng._LIB._handle
    # Read nvar from memory at known offset
    with open(dll_path, 'rb') as f:
        d = f.read()
    e_lfanew = struct.unpack('<I', d[0x3c:0x40])[0]
    arch = struct.unpack('<H', d[e_lfanew+4:e_lfanew+6])[0]
    print('Arch:', hex(arch), flush=True)
    opt_hdr_size = struct.unpack('<H', d[e_lfanew+20:e_lfanew+22])[0]
    sh_off = e_lfanew + 24 + opt_hdr_size
    for i in range(struct.unpack('<H', d[e_lfanew+6:e_lfanew+8])[0]):
        sh = d[sh_off+i*40:sh_off+i*40+40]
        name = sh[:8].rstrip(b'\x00').decode('utf-8', errors='replace')
        if name == '.data':
            data_rva = struct.unpack('<I', sh[12:16])[0]
            print('Data RVA:', hex(data_rva), flush=True)
            break
    buf = (ctypes.c_int * 1)()
    nvar_addr = handle + data_rva + 0x211644
    print('nvar addr:', hex(nvar_addr), flush=True)
    ctypes.memmove(buf, ctypes.c_void_p(nvar_addr), 4)
    print('Direct nvar read:', buf[0], flush=True)
