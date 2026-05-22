"""Narrow down nvar and nobs offsets on Windows by scanning value changes."""
import ctypes
import struct

dll_path = r'C:\Program Files\StataNow19\se-64.dll'
dll = ctypes.WinDLL(dll_path)
handle = dll._handle

# Read PE header to find .data section
buf = (ctypes.c_char * 0x200)()
ctypes.memmove(buf, ctypes.c_void_p(handle), 0x200)
dos = buf.raw[:0x200]
e_lfanew = struct.unpack('<I', dos[0x3c:0x40])[0]

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
        print(f'.data: mem={data_mem:#x}, size={data_size:#x}')
        break

if not data_mem:
    print('No .data section!')
    exit(1)

# Init Stata
_Main = dll.StataSO_Main
_Main.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_char_p)]
_Main.restype = ctypes.c_int
_Main(2, (ctypes.c_char_p * 2)(b'stata', b'-q'))

_Execute = dll.StataSO_Execute
_Execute.argtypes = [ctypes.c_char_p]
_Execute.restype = ctypes.c_int

def read_data():
    """Read the full .data section."""
    buf = (ctypes.c_char * data_size)()
    ctypes.memmove(buf, ctypes.c_void_p(data_mem), data_size)
    return buf.raw

def scan_value(raw, val):
    """Scan for all 4-byte and 8-byte occurrences of val."""
    found = []
    for o in range(0, len(raw) - 8, 4):
        if struct.unpack('<i', raw[o:o+4])[0] == val:
            found.append((o, 32))
        elif struct.unpack('<q', raw[o:o+8])[0] == val:
            found.append((o, 64))
    return found

# Phase 1: Scan with auto dataset
_Execute(b'sysuse auto, clear')
raw_auto = read_data()
print(f'Phase 1: auto dataset (nvar=12, nobs=74) scanned {len(raw_auto)} bytes')

nvar_candidates = scan_value(raw_auto, 12)
nobs_candidates = scan_value(raw_auto, 74)
maxvars_candidates = [o for o in range(0, len(raw_auto)-4, 4) 
                      if struct.unpack('<I', raw_auto[o:o+4])[0] == 5000]

print(f'nvar=12: {len(nvar_candidates)}')
print(f'nobs=74: {len(nobs_candidates)}')
print(f'maxvars=5000: {len(maxvars_candidates)}')

# Phase 2: Switch to bpwide and scan again
_Execute(b'sysuse bpwide, clear')
raw_bpwide = read_data()
print(f'\nPhase 2: bpwide dataset (nvar=5, nobs=36)')

# Check which nvar=12 locations now have value 5
nvar_verified = []
for o, bs in nvar_candidates:
    if bs == 32 and o < len(raw_bpwide) - 4:
        if struct.unpack('<i', raw_bpwide[o:o+4])[0] == 5:
            nvar_verified.append((o, 32))
    elif bs == 64 and o < len(raw_bpwide) - 8:
        if struct.unpack('<q', raw_bpwide[o:o+8])[0] == 5:
            nvar_verified.append((o, 64))

print(f'nvar 12->5: {len(nvar_verified)} verified')
for o, bs in nvar_verified[:10]:
    addr = data_mem + o
    print(f'  offset={o:#010x} ({bs}-bit), addr={addr:#x}')

# Check nobs
# Also check 36 in bpwide
nobs_verified = []
for o in range(0, len(raw_bpwide) - 8, 4):
    v32 = struct.unpack('<i', raw_bpwide[o:o+4])[0]
    v64 = struct.unpack('<q', raw_bpwide[o:o+8])[0]
    is_nvar = any(o == nv for nv, _ in nvar_verified)
    if v32 == 36 and not is_nvar:
        # Check what was here in auto
        v_auto = struct.unpack('<i', raw_auto[o:o+4])[0]
        if v_auto == 74:
            nobs_verified.append((o, 32, v_auto))
    if v64 == 36 and not is_nvar:
        v_auto = struct.unpack('<q', raw_auto[o:o+8])[0]
        if v_auto == 74:
            nobs_verified.append((o, 64, v_auto))

print(f'\nnobs 74->36: {len(nobs_verified)} verified')
for o, bs, prev in nobs_verified[:10]:
    addr = data_mem + o
    print(f'  offset={o:#010x} ({bs}-bit, was {prev}), addr={addr:#x}')

# Also check 5000 locations
print(f'\nmaxvars=5000 locations:')
for o in maxvars_candidates[:10]:
    addr = data_mem + o
    # Verify in bpwide also
    v2 = struct.unpack('<I', raw_bpwide[o:o+4])[0]
    print(f'  offset={o:#010x}, addr={addr:#x}, auto={5000}, bpwide={v2}')

# Phase 3: Test all verified nvar offsets by direct read
print(f'\nPhase 3: Verification by reading nvar directly')
for o, bs in nvar_verified[:5]:
    if bs == 32:
        v = struct.unpack('<i', raw_bpwide[o:o+4])[0]
    else:
        v = struct.unpack('<q', raw_bpwide[o:o+8])[0]
    print(f'  offset={o:#010x} nvar={v} (expected 5 for bpwide)')

# Find close nvar/nobs pairs
print(f'\nClose nvar/nobs pairs:')
nvar_offsets = {o for o, _ in nvar_verified}
nobs_offsets = {o for o, _, _ in nobs_verified}
for no in sorted(nobs_offsets):
    for nv in sorted(nvar_offsets):
        diff = abs(no - nv)
        if 0 < diff < 256:
            print(f'  nobs@{no:#x} nvar@{nv:#x} diff={diff}')

print('\nDone')
