"""Understand data buffer layout relative to .data section.
The sentinel is at data+0x922c00 with 1 var + 1 obs.
Vary the dataset size to see how the data buffer shifts."""
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
num_sections = struct.unpack('<H', pe_data[e_lfanew+6:e_lfanew+8])[0]
for i in range(num_sections):
    sh = pe_data[sh_off + i*40:sh_off + i*40 + 40]
    name = sh[:8].rstrip(b'\x00').decode('utf-8', errors='replace')
    if name == '.data':
        data_rva = struct.unpack('<I', sh[12:16])[0]
        data_vsize = struct.unpack('<I', sh[8:12])[0]
        break
data_ptr = handle + data_rva
print('data_ptr:', hex(data_ptr))

def find_sentinel_in_data(dll, data_ptr, data_vsize, sentinel_val):
    """Search .data section for a double value, return offset or None."""
    s_bytes = struct.pack('<d', sentinel_val)
    chunk_size = 256 * 1024
    for chunk_start in range(0, data_vsize, chunk_size):
        cur_size = min(chunk_size, data_vsize - chunk_start)
        buf = (ctypes.c_char * cur_size)()
        try:
            ctypes.memmove(buf, ctypes.c_void_p(data_ptr + chunk_start), cur_size)
        except:
            return None  # Access violation (trying to read beyond real committed pages)
        chunk_raw = bytes(buf)
        idx = chunk_raw.find(s_bytes)
        if idx >= 0:
            return chunk_start + idx
    return None

print('\n=== Test 1: 1 var, 1 obs ===')
dll.StataSO_Execute(b'clear')
dll.StataSO_Execute(b'set obs 1')
dll.StataSO_Execute(b'gen double __px_sentinel = 12345.6789')
off1 = find_sentinel_in_data(dll, data_ptr, data_vsize, 12345.6789)
print('  sentinel at data+%x' % off1)
# nvar
nv_buf = (ctypes.c_int * 1)()
ctypes.memmove(nv_buf, ctypes.c_void_p(data_ptr + 0x211644), 4)
print('  nvar:', nv_buf[0])
# Read nearby - what's around the sentinel?
buf = (ctypes.c_char * 256)()
ctypes.memmove(buf, ctypes.c_void_p(data_ptr + off1 - 64), 256)
raw = bytes(buf)
for k in range(0, 256, 8):
    val = struct.unpack('<d', raw[k:k+8])[0]
    val_int = struct.unpack('<Q', raw[k:k+8])[0]
    marker = ' <-- SENTINEL' if k == 64 else ''
    addr = data_ptr + off1 - 64 + k
    print('  [%s] %.1f (0x%x)%s' % ('%+d' % (k - 64), val, val_int, marker))

print('\n=== Test 2: 3 vars, 2 obs ===')
dll.StataSO_Execute(b'clear')
dll.StataSO_Execute(b'set obs 2')
dll.StataSO_Execute(b'gen double __px_a = 12345.6789')
dll.StataSO_Execute(b'gen double __px_b = 112233.4455')
dll.StataSO_Execute(b'gen double __px_c = 998877.6655')

off2a = find_sentinel_in_data(dll, data_ptr, data_vsize, 12345.6789)
off2b = find_sentinel_in_data(dll, data_ptr, data_vsize, 112233.4455)
off2c = find_sentinel_in_data(dll, data_ptr, data_vsize, 998877.6655)
print('  sentinel_a at data+%s' % ('None' if off2a is None else hex(off2a)))
print('  sentinel_b at data+%s' % ('None' if off2b is None else hex(off2b)))
print('  sentinel_c at data+%s' % ('None' if off2c is None else hex(off2c)))
if None not in (off2a, off2b, off2c):
    print('  deltas: a-c=%d obs stride=%d' % (off2a - off2c, off2a - off2b))

# nvar
ctypes.memmove(nv_buf, ctypes.c_void_p(data_ptr + 0x211644), 4)
print('  nvar:', nv_buf[0])

print('\n=== Test 3: 1 var, 5 obs ===')
dll.StataSO_Execute(b'clear')
dll.StataSO_Execute(b'set obs 5')
dll.StataSO_Execute(b'gen double __px_sentinel = 12345.6789')
off3 = find_sentinel_in_data(dll, data_ptr, data_vsize, 12345.6789)
print('  sentinel at data+%x' % off3)
ctypes.memmove(nv_buf, ctypes.c_void_p(data_ptr + 0x211644), 4)
print('  nvar:', nv_buf[0])

# Also try auto dataset
print('\n=== Test 4: auto dataset ===')
dll.StataSO_Execute(b'clear')
rc = dll.StataSO_Execute(b'sysuse auto, clear')
print('  sysuse rc:', rc)
ctypes.memmove(nv_buf, ctypes.c_void_p(data_ptr + 0x211644), 4)
print('  nvar:', nv_buf[0])

# Where is price (var 1) for obs 0? It should be 4099.
off_price = find_sentinel_in_data(dll, data_ptr, data_vsize, 4099.0)
off_mpg = find_sentinel_in_data(dll, data_ptr, data_vsize, 22.0)
print('  price (4099) at data+%s' % ('None' if off_price is None else hex(off_price)))
print('  mpg (22) at data+%s' % ('None' if off_mpg is None else hex(off_mpg)))
if off_price and off_mpg:
    print('  delta price-mpg: %d' % (off_price - off_mpg))

print('\nDone')
