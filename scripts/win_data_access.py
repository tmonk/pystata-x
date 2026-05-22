"""Find actual data buffer by searching for known values."""
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
        raw_size = struct.unpack('<I', sh[16:20])[0]
        break
data_ptr = handle + data_rva
print('data_rva:', hex(data_rva), 'vsize:', data_vsize, 'raw:', raw_size)

def find_double_in_range(start_off, size, target_val):
    """Find a double value within a memory range."""
    s_bytes = struct.pack('<d', target_val)
    for cs in range(0, size, 256*1024):
        cur = min(256*1024, size - cs)
        try:
            buf = (ctypes.c_char * cur)()
            ctypes.memmove(buf, ctypes.c_void_p(data_ptr + start_off + cs), cur)
        except:
            continue
        idx = bytes(buf).find(s_bytes)
        if idx >= 0:
            return start_off + cs + idx
    return None

# Load auto
dll.StataSO_Execute(b'sysuse auto, clear')
nv_buf = (ctypes.c_int * 1)()
ctypes.memmove(nv_buf, ctypes.c_void_p(data_ptr + 0x211644), 4)
print('nvar:', nv_buf[0])

# Search for price[1]=4099 in the FULL committed data section
print('\nSearching for price[1]=4099 in full .data...')
# First find the committed pages (not virtual memory that's uncommitted)
# On Windows, committed pages are the ones we can read. Try the raw file size first.
result = find_double_in_range(0, min(raw_size, data_vsize), 4099.0)
if result is not None:
    print('  Found at data+%x' % result)
else:
    print('  Not in raw-size range. Trying full virtual size...')
    result = find_double_in_range(0, data_vsize, 4099.0)
    if result is not None:
        print('  Found at data+%x' % result)
    else:
        print('  Not in .data section at all! Data buffer is on heap.')

# Also search for mpg[1]=22 and rep78[1]=3
for label, val in [('mpg[1]', 22.0), ('rep78[1]', 3.0), ('weight[1]', 2930.0), ('length[1]', 186.0)]:
    off = find_double_in_range(0, min(raw_size, data_vsize), val)
    if off is None:
        off = find_double_in_range(0, data_vsize, val)
    print('  %s=%.0f at %s' % (label, val, 'data+%x' % off if off else 'NOT FOUND'))

if result:
    # Read around the found value to understand data layout
    print('\n=== Buffer layout around price[1] ===')
    nearby = (ctypes.c_double * 50)()
    base = result - 200
    if base < 0: base = 0
    try:
        ctypes.memmove(nearby, ctypes.c_void_p(data_ptr + base), 400)
    except:
        nearby = (ctypes.c_double * 50)()
        ctypes.memmove(nearby, ctypes.c_void_p(data_ptr + result - 100), 400)
        base = result - 100
    for k in range(50):
        if nearby[k] != 0:
            print('  [%+d] %.0f' % (base + k*8 - result, nearby[k]))

# If NOT in .data, try other sections
if result is None:
    print('\n=== Data buffer is NOT in .data. Searching other sections... ===')
    # Try reading beyond raw_size but within committed virtual memory
    # Windows may have committed more pages
    print('Searching extended .data region (vsize=%d)...' % data_vsize)
    for _, val in [('', 4099.0), ('', 22.0), ('', 2930.0), ('', 3.0)]:
        s_bytes = struct.pack('<d', val)
        for cs in range(0, data_vsize, 1024*1024):
            cur = min(1024*1024, data_vsize - cs)
            try:
                buf = (ctypes.c_char * cur)()
                ctypes.memmove(buf, ctypes.c_void_p(data_ptr + cs), cur)
            except:
                continue
            if s_bytes in bytes(buf):
                print('  Found %.0f at data+%x' % (val, cs + bytes(buf).find(s_bytes)))

print('\nDone')
