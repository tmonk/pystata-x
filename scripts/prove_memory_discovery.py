"""Prove pe memory discovery works step by step, then integrate into framework."""
import ctypes
import struct
import json
import sys

result = {}  # accumulate results

# 1. Load DLL
dll_path = r'C:\Program Files\StataNow19\se-64.dll'
dll = ctypes.WinDLL(dll_path)
handle = dll._handle
result['handle'] = hex(handle)

# 2. Init Stata
dll.StataSO_Main.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_char_p)]
dll.StataSO_Main.restype = ctypes.c_int
argv = (ctypes.c_char_p * 2)(b'stata', b'-q')
rc = dll.StataSO_Main(2, argv)
result['init_rc'] = rc

# 3. Get Execute
dll.StataSO_Execute.argtypes = [ctypes.c_char_p]
dll.StataSO_Execute.restype = ctypes.c_int
result['exec_works'] = dll.StataSO_Execute(b'capture noi disp "hello"') == 0
result['hello_rc'] = dll.StataSO_Execute(b'capture noi disp "hello"')

# 4. Find .data section
with open(dll_path, 'rb') as f:
    pe_data = f.read()
e_lfanew = struct.unpack('<I', pe_data[0x3c:0x40])[0]
num_sections = struct.unpack('<H', pe_data[e_lfanew+6:e_lfanew+8])[0]
opt_hdr_size = struct.unpack('<H', pe_data[e_lfanew+20:e_lfanew+22])[0]
sh_off = e_lfanew + 24 + opt_hdr_size

data_rva = 0
for i in range(num_sections):
    sh = pe_data[sh_off+i*40:sh_off+i*40+40]
    name = sh[:8].rstrip(b'\x00').decode('utf-8', errors='replace')
    if name == '.data':
        data_rva = struct.unpack('<I', sh[12:16])[0]
        break

data_ptr = handle + data_rva
result['data_ptr'] = hex(data_ptr)
result['data_rva'] = hex(data_rva)

# 5. Load dataset
dll.StataSO_Execute(b'sysuse auto, clear')
result['load_auto_rc'] = dll.StataSO_Execute(b'sysuse auto, clear')

# 6. Read nvar at known offset
KNOWN_NVAR_OFFSET = 0x211644
buf = (ctypes.c_int * 1)()
ctypes.memmove(buf, ctypes.c_void_p(data_ptr + KNOWN_NVAR_OFFSET), 4)
nvar = buf[0]
result['nvar_raw'] = nvar

if nvar != 12:
    result['error'] = 'nvar offset wrong: expected 12 got %d' % nvar
    sys.stdout.write(json.dumps(result, indent=2) + '\n')
    sys.stdout.flush()
    sys.exit(1)

# 7. Compute gws pointer (gws.nvar at +0x68 on both Linux and Windows)
gws_ptr = data_ptr + KNOWN_NVAR_OFFSET - 0x68
result['gws_ptr'] = hex(gws_ptr)

# 8. Read gws fields with auto dataset
def read_gws():
    """Read all int32 fields from gws."""
    fields = {}
    for off in range(0, 256, 4):
        b = (ctypes.c_int * 1)()
        ctypes.memmove(b, ctypes.c_void_p(gws_ptr + off), 4)
        val = b[0]
        if 0 < val < 200000:
            fields[off] = val
    return fields

fields_auto = read_gws()

# 9. Load bpwide and read again
dll.StataSO_Execute(b'sysuse bpwide, clear')
fields_bpwide = read_gws()

# 10. Find changing fields
memory_offsets = {}
for off in sorted(fields_auto):
    v1 = fields_auto[off]
    v2 = fields_bpwide.get(off, 0)
    if v1 != v2:
        if v1 == 74 and v2 == 36:
            memory_offsets['nobs_offset'] = off
            memory_offsets['nobs_gws_offset'] = off
        if v1 == 12 and v2 == 5:
            memory_offsets['nvar_offset'] = off
            memory_offsets['nvar_gws_offset'] = off

# 11. Find maxvars (5000)
for o in range(0, 921088 - 4, 4):
    if struct.unpack('<I', pe_data[data_rva + o - data_rva_ofs...])):
        ...

# Actually read from loaded memory
data_size = 921088
raw_buf = (ctypes.c_char * data_size)()
ctypes.memmove(raw_buf, ctypes.c_void_p(data_ptr), data_size)
raw = bytes(raw_buf)

for o in range(0, data_size - 4, 4):
    if struct.unpack('<I', raw[o:o+4])[0] == 5000:
        memory_offsets['maxvars_offset'] = o
        break

# 12. Restore auto
dll.StataSO_Execute(b'sysuse auto, clear')

result['memory_offsets'] = memory_offsets
result['gws_fields_auto_sample'] = dict(list(fields_auto.items())[:10])
result['gws_fields_bpwide_sample'] = dict(list(fields_bpwide.items())[:10])

sys.stdout.write(json.dumps(result, indent=2) + '\n')
sys.stdout.flush()
