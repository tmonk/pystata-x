"""Discover Stata memory offsets on Windows via data section scanning."""
import ctypes
import struct

dll_path = r'C:\Program Files\StataNow19\se-64.dll'
dll = ctypes.WinDLL(dll_path)
handle = dll._handle

# Read DOS header
buf = (ctypes.c_char * 0x200)()
ctypes.memmove(buf, ctypes.c_void_p(handle), 0x200)
dos = buf.raw[:0x200]
e_lfanew = struct.unpack('<I', dos[0x3c:0x40])[0]

# Read PE header
pe_buf = (ctypes.c_char * 0x200)()
ctypes.memmove(pe_buf, ctypes.c_void_p(handle + e_lfanew), 0x200)
pe = pe_buf.raw[:0x200]

file_header = pe[4:24]
num_sections = struct.unpack('<H', file_header[2:4])[0]
opt_hdr_size = struct.unpack('<H', file_header[16:18])[0]
sections_base = handle + e_lfanew + 24 + opt_hdr_size

magic = struct.unpack('<H', pe[24:26])[0]
print(f'Magic: {magic:#x} ({ "PE32+" if magic == 0x20b else "PE32" if magic == 0x10b else "?" })')

sections = []
for i in range(num_sections):
    sh_buf = (ctypes.c_char * 40)()
    ctypes.memmove(sh_buf, ctypes.c_void_p(sections_base + i * 40), 40)
    sh = sh_buf.raw[:40]
    name = sh[:8].rstrip(b'\x00').decode(errors='replace')
    virtual_size = struct.unpack('<I', sh[8:12])[0]
    virtual_address = struct.unpack('<I', sh[12:16])[0]
    mem_ptr = handle + virtual_address
    sections.append({
        'name': name, 'va': virtual_address, 'size': virtual_size, 'mem_ptr': mem_ptr
    })
    print(f'  {name}: VA={virtual_address:#010x} mem={mem_ptr:#x} size={virtual_size:#x}')

# Initialize Stata
_Main = dll.StataSO_Main
_Main.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_char_p)]
_Main.restype = ctypes.c_int
argv = (ctypes.c_char_p * 2)(b'stata', b'-q')
_Main(2, argv)

_Execute = dll.StataSO_Execute
_Execute.argtypes = [ctypes.c_char_p]
_Execute.restype = ctypes.c_int

# Load auto dataset
_Execute(b'sysuse auto, clear')
print('\nDataset: auto (nvar=12, nobs=74)')

# Find data section
data_sec = None
for s in sections:
    if s['name'] == '.data':
        data_sec = s
        break

if data_sec:
    sz = data_sec['size']
    mem = data_sec['mem_ptr']
    print(f'\n.data at {mem:#x}, size={sz}')
    
    data_buf = (ctypes.c_char * sz)()
    ctypes.memmove(data_buf, ctypes.c_void_p(mem), sz)
    raw = data_buf.raw
    
    # Scan for value 12 (nvar)
    found_12 = [(o, 32) for o in range(0, sz-4, 4) 
                if struct.unpack('<i', raw[o:o+4])[0] == 12]
    found_12 += [(o, 64) for o in range(0, sz-8, 4)
                 if struct.unpack('<q', raw[o:o+8])[0] == 12]
    print(f'nvar=12: {len(found_12)} locations')
    
    # Scan for value 74 (nobs)
    found_74 = [(o, 32, struct.unpack('<i', raw[o:o+4])[0]) 
                for o in range(0, sz-4, 4)
                if struct.unpack('<i', raw[o:o+4])[0] == 74]
    found_74 += [(o, 64, struct.unpack('<q', raw[o:o+8])[0])
                 for o in range(0, sz-8, 4) 
                 if struct.unpack('<q', raw[o:o+8])[0] == 74]
    print(f'nobs=74: {len(found_74)} locations')
    
    # Scan for maxvars=5000
    found_5000 = [o for o in range(0, sz-4, 4) 
                  if struct.unpack('<I', raw[o:o+4])[0] == 5000]
    print(f'maxvars=5000: {len(found_5000)} locations')
    
    # Now change dataset to bpwide (nvar=5, nobs=36)
    _Execute(b'sysuse bpwide, clear')
    print('\nDataset: bpwide (nvar=5, nobs=36)')
    
    # Re-read data section
    ctypes.memmove(data_buf, ctypes.c_void_p(mem), sz)
    raw2 = data_buf.raw
    
    # Filter candidate nvar locations (was 12, now 5)
    changed_to_5 = []
    for o, bs in found_12:
        if bs == 32 and o < sz-4:
            v = struct.unpack('<i', raw2[o:o+4])[0]
            if v == 5:
                changed_to_5.append((o, bs, v))
        elif bs == 64 and o < sz-8:
            v = struct.unpack('<q', raw2[o:o+8])[0]
            if v == 5:
                changed_to_5.append((o, bs, v))
    print(f'nvar 12->5: {len(changed_to_5)} candidates')
    for o, bs, v in changed_to_5[:10]:
        abs_addr = mem + o
        print(f'  offset={o:#010x} ({bs}-bit, val={v}), addr={abs_addr:#x}')
    
    # Filter candidate nobs locations (was 74, now 36)
    changed_to_36 = []
    for o, bs, _ in found_74:
        if bs == 32 and o < sz-4:
            v = struct.unpack('<i', raw2[o:o+4])[0]
            if v == 36:
                changed_to_36.append((o, v))
        elif bs == 64 and o < sz-8:
            v = struct.unpack('<q', raw2[o:o+8])[0]
            if v == 36:
                changed_to_36.append((o, v))
    print(f'\nnobs 74->36: {len(changed_to_36)} candidates')
    for o, v in changed_to_36[:10]:
        abs_addr = mem + o
        print(f'  offset={o:#010x} (val={v}), addr={abs_addr:#x}')
    
    # Find which nvar/nobs pairs are close together (within 256 bytes)
    nvar_cands = {o for o, bs, _ in changed_to_5}
    nobs_cands = {o for o, _ in changed_to_36}
    print(f'\nNvar/nobs pairs within 256 bytes:')
    for no in sorted(nobs_cands):
        for nv in sorted(nvar_cands):
            diff = abs(no - nv)
            if 0 < diff < 256:
                print(f'  nobs@{no:#x} nvar@{nv:#x} diff={diff}')
    
    # Also verify maxvars hasn't changed
    _Execute(b'sysuse auto, clear')
    print('\nVerified: back to auto dataset')

print('\nDone')
