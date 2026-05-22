"""Find nobs offset by scanning forward from nvar candidates."""
import ctypes
import struct

dll_path = r'C:\Program Files\StataNow19\se-64.dll'
dll = ctypes.WinDLL(dll_path)
handle = dll._handle

# Find .data section
buf = (ctypes.c_char * 0x200)()
ctypes.memmove(buf, ctypes.c_void_p(handle), 0x200)
e_lfanew = struct.unpack('<I', buf.raw[0x3c:0x40])[0]

pe_buf = (ctypes.c_char * 0x200)()
ctypes.memmove(pe_buf, ctypes.c_void_p(handle + e_lfanew), 0x200)
pe = pe_buf.raw[:0x200]

file_header = pe[4:24]
num_sections = struct.unpack('<H', file_header[2:4])[0]
opt_hdr_size = struct.unpack('<H', file_header[16:18])[0]
sections_base = handle + e_lfanew + 24 + opt_hdr_size

data_mem = None
data_size = 0
for i in range(num_sections):
    sh_buf = (ctypes.c_char * 40)()
    ctypes.memmove(sh_buf, ctypes.c_void_p(sections_base + i * 40), 40)
    sh = sh_buf.raw[:40]
    name = sh[:8].rstrip(b'\x00').decode(errors='replace')
    if name == '.data':
        va = struct.unpack('<I', sh[12:16])[0]
        vs = struct.unpack('<I', sh[8:12])[0]
        data_mem = handle + va
        data_size = vs
        break

# Init Stata
_Main = dll.StataSO_Main
_Main.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_char_p)]
_Main.restype = ctypes.c_int
_Main(2, (ctypes.c_char_p * 2)(b'stata', b'-q'))

_Execute = dll.StataSO_Execute
_Execute.argtypes = [ctypes.c_char_p]
_Execute.restype = ctypes.c_int

def read_data():
    buf = (ctypes.c_char * data_size)()
    ctypes.memmove(buf, ctypes.c_void_p(data_mem), data_size)
    return buf.raw

# Scan around nvar offset for nobs
# On Linux: gws.nvar at offset, gws.nobs at offset-8 or +some_delta
# On Windows, look at the area near nvar candidates

nvar_candidates = [
    0x00211644,   # candidate 1
    0x00225b98,   # candidate 2
    0x00b4a880,   # candidate 3
]

print('=== Strategy A: Scan near nvar candidates ===')
_Execute(b'sysuse auto, clear')
raw_auto = read_data()

_Execute(b'sysuse bpwide, clear')
raw_bpwide = read_data()

# For each nvar candidate, scan the surrounding 256 bytes for nobs-like values
for nv_off in nvar_candidates:
    print(f'\nNvar at offset {nv_off:#010x}:')
    for delta in range(-256, 257, 4):
        off = nv_off + delta
        if off < 0 or off + 8 > len(raw_auto):
            continue
        # Check what values appear. Nobs could be int64, float64, or int32
        auto_i32 = struct.unpack('<i', raw_auto[off:off+4])[0]
        bpwide_i32 = struct.unpack('<i', raw_bpwide[off:off+4])[0]
        auto_f64 = struct.unpack('<d', raw_auto[off:off+8])[0]
        bpwide_f64 = struct.unpack('<d', raw_bpwide[off:off+8])[0]
        
        # Nobs changed from 74 to 36
        # Check int32
        if auto_i32 == 74 and bpwide_i32 == 36:
            print(f'  INT32: nobs@{off:#x} (delta={delta}) -> {auto_i32}')
        # Check float64  
        if abs(auto_f64 - 74.0) < 0.001 and abs(bpwide_f64 - 36.0) < 0.001:
            print(f'  FLOAT64: nobs@{off:#x} (delta={delta}) -> {auto_f64}')
        # Check int64
        auto_i64 = struct.unpack('<q', raw_auto[off:off+8])[0]
        bpwide_i64 = struct.unpack('<q', raw_bpwide[off:off+8])[0]
        if auto_i64 == 74 and bpwide_i64 == 36:
            print(f'  INT64: nobs@{off:#x} (delta={delta})')

# Strategy B: Global scan for ANY variable that changes from 74 to 36
print('\n=== Strategy B: Full scan for 74->36 transition ===')
print('Scanning for float64 = 74.0...')
for o in range(0, len(raw_auto) - 8, 8):
    auto_f64 = struct.unpack('<d', raw_auto[o:o+8])[0]
    bpwide_f64 = struct.unpack('<d', raw_bpwide[o:o+8])[0]
    if abs(auto_f64 - 74.0) < 0.001 and abs(bpwide_f64 - 36.0) < 0.001:
        print(f'  FLOAT64 nobs@{o:#x}, addr={data_mem + o:#x}')

# Strategy C: Use r-class query
print('\n=== Strategy C: Compare with r-class retrieval ===')
# Can we get nobs via _bist-less approach on Windows?
# Use ereturn/scalar approach
_Execute(b'quietly sum price')
_Execute(b'gen double __px_N = r(N)')
_Execute(b'scalar __px_N = __px_N[1]')

# Read the scalar value from memory
# On Windows, the scalar values are stored in the data area
# Let's create a scalar and find its value by scanning
_Execute(b'scalar nobs_test = 99')
_Execute(b'di scalar(nobs_test)')

# Read scalar area - search for 99
raw_now = read_data()
found_99 = []
for o in range(0, len(raw_now) - 8, 4):
    v32 = struct.unpack('<i', raw_now[o:o+4])[0]
    v64 = struct.unpack('<q', raw_now[o:o+8])[0]
    if v32 == 99:
        found_99.append((o, 32))
    elif v64 == 99:
        found_99.append((o, 64))

print(f'Scalar test@99: {len(found_99)} matches')
for o, bs in found_99[:10]:
    print(f'  offset={o:#010x} ({bs}-bit), addr={data_mem+o:#x}')

# Now change the scalar and check what changes
_Execute(b'scalar nobs_test = 88')
raw_88 = read_data()
conserved = []
for o, bs in found_99:
    if bs == 32:
        v = struct.unpack('<i', raw_88[o:o+4])[0]
        if v == 88:
            conserved.append(o)
    else:
        v = struct.unpack('<q', raw_88[o:o+8])[0]
        if v == 88:
            conserved.append(o)
print(f'\nScalar 99->88: {len(conserved)} conserved')
for o in conserved:
    print(f'  offset={o:#010x}, addr={data_mem+o:#x}')

print('\nDone')
