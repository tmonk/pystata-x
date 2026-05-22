"""Verify data buffer at 0x922C00 stores ALL variables correctly."""
import ctypes
import struct

dll_path = r'C:\Program Files\StataNow19\se-64.dll'
dll = ctypes.WinDLL(dll_path)
handle = dll._handle

dll.StataSO_Main.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_char_p)]
dll.StataSO_Main.restype = ctypes.c_int
dll.StataSO_Main(2, (ctypes.c_char_p * 2)(b'stata', b'-q'))
dll.StataSO_Execute.argtypes = [ctypes.c_char_p]
dll.StataSO_Execute.restype = ctypes.c_int

with open(dll_path, 'rb') as f:
    pe_data = f.read()
e_lfanew = struct.unpack('<I', pe_data[0x3c:0x40])[0]
opt_hdr_size = struct.unpack('<H', pe_data[e_lfanew+20:e_lfanew+22])[0]
sh_off = e_lfanew + 24 + opt_hdr_size
for i in range(struct.unpack('<H', pe_data[e_lfanew+6:e_lfanew+8])[0]):
    sh = pe_data[sh_off + i*40:sh_off + i*40 + 40]
    name = sh[:8].rstrip(b'\x00').decode('utf-8', errors='replace')
    if name == '.data':
        data_rva = struct.unpack('<I', sh[12:16])[0]
        data_vsize = struct.unpack('<I', sh[8:12])[0]
        break
data_ptr = handle + data_rva
print('data_ptr:', hex(data_ptr))

def find_all_occurrences(target_val, limit=5):
    """Find all occurrences of a double value in .data section."""
    s_bytes = struct.pack('<d', target_val)
    results = []
    for cs in range(0, data_vsize, 256*1024):
        cur = min(256*1024, data_vsize - cs)
        try:
            buf = (ctypes.c_char * cur)()
            ctypes.memmove(buf, ctypes.c_void_p(data_ptr + cs), cur)
        except:
            continue
        raw = bytes(buf)
        # Find all occurrences
        pos = 0
        while True:
            idx = raw.find(s_bytes, pos)
            if idx < 0:
                break
            results.append(cs + idx)
            pos = idx + 8
            if len(results) >= limit:
                return results
    return results

def read_int(offset):
    """Read a 4-byte int from data section."""
    buf = (ctypes.c_int * 1)()
    ctypes.memmove(buf, ctypes.c_void_p(data_ptr + offset), 4)
    return buf[0]

# === Test 1: auto dataset ===
print('\n=== Test: sysuse auto ===')
dll.StataSO_Execute(b'sysuse auto, clear')
print('nvar:', read_int(0x211644))
nv_buf = (ctypes.c_int * 1)()
ctypes.memmove(nv_buf, ctypes.c_void_p(data_ptr + 0x211644), 4)
nvar = nv_buf[0]
print('nvar:', nvar)

# Find price (should be 4099) data+0x922C00 should contain it
print('Searching for price (4099)...')
price_locs = find_all_occurrences(4099.0, 3)
for loc in price_locs:
    print('  Price at data+%x' % loc)
    # Check what other values are near this location
    buf = (ctypes.c_double * 20)()
    read_addr = data_ptr + loc - 80  # Read 20 doubles starting 80 bytes before
    ctypes.memmove(buf, ctypes.c_void_p(read_addr), 160)
    print('  Values around it:')
    for k in range(20):
        if abs(buf[k] - 4099) < 0.1:
            marker = ' <-- PRICE'
        elif buf[k] != 0:
            marker = ' (%.1f)' % buf[k]
        else:
            marker = ''
        if marker:
            print('    [%+d] %.0f%s' % (k - 10, buf[k], marker))

# === Test 2: Create clean dataset with multiple vars ===
print('\n=== Test: 3 vars, 2 obs ===')
dll.StataSO_Execute(b'clear')
dll.StataSO_Execute(b'set obs 2')
dll.StataSO_Execute(b'gen double __px_a = 1111.2222')
dll.StataSO_Execute(b'gen double __px_b = 3333.4444')
dll.StataSO_Execute(b'gen double __px_c = 5555.6666')

print('nvar:', read_int(0x211644))
nv_buf = (ctypes.c_int * 1)()
ctypes.memmove(nv_buf, ctypes.c_void_p(data_ptr + 0x211644), 4)
print('nvar:', nv_buf[0])

for label, val in [('a', 1111.2222), ('b', 3333.4444), ('c', 5555.6666)]:
    locs = find_all_occurrences(val, 5)
    print('  __px_%s (%.4f): found at %d locations' % (label, val, len(locs)))
    for loc in locs[:3]:
        print('    data+%x' % loc)

# Check the data buffer at 0x922C00
print('\n=== Reading data buffer at 0x922C00 ===')
STATIC_BUF_OFF = 0x922C00
buf = (ctypes.c_double * 100)()
ctypes.memmove(buf, ctypes.c_void_p(data_ptr + STATIC_BUF_OFF), 800)
non_zero = [(i, buf[i]) for i in range(100) if buf[i] != 0]
print('Non-zero values at 0x922C00:')
for idx, val in non_zero[:20]:
    print('  [+%d] %f' % (idx * 8, val))

# Now test: does 0x922C00 support obs*var indexing?
print('\nTrying data_get(obs, var) via 0x922C00 buffer:')
raw_buf = (ctypes.c_char * 256)()
ctypes.memmove(raw_buf, ctypes.c_void_p(data_ptr + STATIC_BUF_OFF), 256)
raw = bytes(raw_buf)
for obs in range(2):
    for var in range(3):
        col_major_off = (var * 2 + obs) * 8
        row_major_off = (obs * 3 + var) * 8
        val_cm = struct.unpack('<d', raw[col_major_off:col_major_off+8])[0]
        val_rm = struct.unpack('<d', raw[row_major_off:row_major_off+8])[0]
        expected = [1111.2222, 3333.4444, 5555.6666][var]
        match_cm = 'MATCH' if abs(val_cm - expected) < 0.01 else ''
        match_rm = 'MATCH' if abs(val_rm - expected) < 0.01 else ''
        print('  [obs=%d var=%d] col-major(off=%d)=%.4f %s | row-major(off=%d)=%.4f %s' 
              % (obs, var, col_major_off, val_cm, match_cm, row_major_off, val_rm, match_rm))

print('\nDone')
