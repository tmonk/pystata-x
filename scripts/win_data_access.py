"""Verify the data+0x5d8 value isn't a false positive and find real data buffer."""
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

def find_double(target_val):
    """Search full data section for a double, return offset or None."""
    s_bytes = struct.pack('<d', target_val)
    for cs in range(0, data_vsize, 256*1024):
        cur = min(256*1024, data_vsize - cs)
        try:
            buf = (ctypes.c_char * cur)()
            ctypes.memmove(buf, ctypes.c_void_p(data_ptr + cs), cur)
        except:
            continue
        idx = bytes(buf).find(s_bytes)
        if idx >= 0:
            return cs + idx
    return None

# Read what's at data+0x5D8
print('=== Reading around data+0x5d8 ===')
buf = (ctypes.c_double * 50)()
try:
    ctypes.memmove(buf, ctypes.c_void_p(data_ptr + 0x5D8 - 200), 400)
except:
    ctypes.memmove(buf, ctypes.c_void_p(data_ptr + 0x5D8), 8)
    print('  0x5d8: %.0f' % buf[0])
else:
    for k in range(50):
        if buf[k] != 0:
            print('  [%+d] %.0f' % (0x5D8 - 200 + k*8, buf[k]))

# Load auto and check specific known values
print('\n=== After loading auto ===')
dll.StataSO_Execute(b'sysuse auto, clear')
nv_buf = (ctypes.c_int * 1)()
ctypes.memmove(nv_buf, ctypes.c_void_p(data_ptr + 0x211644), 4)
print('nvar:', nv_buf[0])

# Check all 12 values for obs[1]
check_vals = [(1, 4099.0), (2, 22.0), (3, 3.0), (4, 2.5), (5, 11.0), 
              (6, 2930.0), (7, 186.0), (8, 40.0), (9, 157.0), 
              (10, 3.58), (11, 0.0), (12, None)]  # var 12 is make (string)

for var, expected in check_vals:
    if expected is None:
        continue
    off = find_double(expected)
    print('  var%d (%.1f): at data+%x' % (var, expected, off if off else 0))
    if off:
        # Check if the next observation in the same variable is nearby
        # If column-major: next obs is at current + 8
        # If row-major: next obs is at current + nvar*8
        row_major_next = data_ptr + off + nv_buf[0] * 8
        col_major_next = data_ptr + off + 1 * 8
        try:
            buf_next = (ctypes.c_double * 2)()
            ctypes.memmove(buf_next, ctypes.c_void_p(row_major_next), 16)
            if buf_next[0] != 0:
                print('    row-major next obs: %.0f' % buf_next[0])
            ctypes.memmove(buf_next, ctypes.c_void_p(col_major_next), 16)
            if buf_next[0] != 0:
                print('    col-major next obs: %.0f' % buf_next[0])
        except:
            pass

# Check: maybe the values for obs[1] are stored together 
# (all 11 numeric vars' obs 1 values are adjacent)
print('\n=== Check proximity: are all obs[0] values adjacent? ===')
off_price = find_double(4099.0)
off_mpg = find_double(22.0)
off_rep78 = find_double(3.0)
if off_price and off_mpg and off_rep78:
    print('  price at data+%x' % off_price)
    print('  mpg at data+%x' % off_mpg)
    print('  rep78 at data+%x' % off_rep78)
    print('  delta price-mpg: %d' % (off_mpg - off_price))
    print('  delta mpg-rep78: %d' % (off_rep78 - off_mpg))
    
    # If row-major with 11 numeric vars: stride = 11*8 = 88
    # mpg should be at price + 8 (adjacent, col-major)
    # or at price + 88 (row-major, next row)
    print('  Expected adj (col-major): %d' % (off_price + 8))
    print('  Expected row-major: %d' % (off_price + 88))

# If most values are NOT in .data, they must be heap.
# Try a different approach: create a UNIQUE value and find it in memory
print('\n=== Creating unique value for heap search ===')
import random
unique_val = 123456.789
dll.StataSO_Execute(b'clear')
dll.StataSO_Execute(b'set obs 1000')
dll.StataSO_Execute(b'gen double __px = ' + str(unique_val).encode())

# Search .data first
s_bytes = struct.pack('<d', unique_val)
in_data = find_double(unique_val)
if in_data:
    print('  Unique value IN .data at +%x' % in_data)
else:
    print('  Unique value NOT in .data (must be on heap)')
    
    # Search full process memory via VirtualQuery
    MEM_COMMIT = 0x1000
    MEM_PRIVATE = 0x20000
    kernel32 = ctypes.windll.kernel32
    
    import ctypes.wintypes as w
    class MEMORY_BASIC_INFORMATION(ctypes.Structure):
        _fields_ = [("BaseAddress", ctypes.c_void_p),
                    ("AllocationBase", ctypes.c_void_p),
                    ("AllocationProtect", ctypes.c_ulong),
                    ("RegionSize", ctypes.c_size_t),
                    ("State", ctypes.c_ulong),
                    ("Protect", ctypes.c_ulong),
                    ("Type", ctypes.c_ulong)]
    
    mbi = MEMORY_BASIC_INFORMATION()
    mbi_size = ctypes.sizeof(MEMORY_BASIC_INFORMATION)
    VirtualQuery = kernel32.VirtualQuery
    VirtualQuery.restype = ctypes.c_size_t
    VirtualQuery.argtypes = [ctypes.c_void_p, ctypes.POINTER(MEMORY_BASIC_INFORMATION), ctypes.c_size_t]
    
    print('\n  Searching process heap memory...')
    addr = ctypes.c_void_p(0x10000)  # Start from low address
    found = False
    while addr.value < 0x7FFFFFFF0000:
        res = VirtualQuery(addr, ctypes.byref(mbi), mbi_size)
        if res == 0:
            break
        if (mbi.State & MEM_COMMIT and 
            mbi.Type == MEM_PRIVATE and
            mbi.Protect == 0x04):  # PAGE_READWRITE
            # Skip DLL region
            if handle <= mbi.BaseAddress < handle + 0x04000000:
                addr = ctypes.c_void_p(mbi.BaseAddress + mbi.RegionSize)
                continue
            # This is a committed, private, read-write region (heap)
            # Search for our value
            try:
                buf = (ctypes.c_char * min(mbi.RegionSize, 256*1024))()
                ctypes.memmove(buf, ctypes.c_void_p(mbi.BaseAddress), min(mbi.RegionSize, 256*1024))
                raw = bytes(buf)
                if s_bytes in raw:
                    idx = raw.find(s_bytes)
                    print('  FOUND at %x (offset %d in region %x-%x)' 
                          % (mbi.BaseAddress + idx, idx, mbi.BaseAddress, mbi.BaseAddress + mbi.RegionSize))
                    # Now search .data for a pointer to this address
                    buf_addr = mbi.BaseAddress + idx
                    # Search first 4MB of .data for pointers to this area
                    print('  Searching .data for pointers to %x...' % buf_addr)
                    for cs in range(0, min(data_vsize, 4*1024*1024), 256*1024):
                        cur = min(256*1024, data_vsize - cs)
                        try:
                            dbuf = (ctypes.c_char * cur)()
                            ctypes.memmove(dbuf, ctypes.c_void_p(data_ptr + cs), cur)
                        except:
                            continue
                        draw = bytes(dbuf)
                        for j in range(0, len(draw) - 8, 8):
                            val = struct.unpack('<Q', draw[j:j+8])[0]
                            if abs(val - buf_addr) < 0x1000:  # Within 4KB
                                print('    POINTER at .data+%x: %x (delta %+d)' 
                                      % (cs + j, val, val - buf_addr))
                    found = True
                    break
            except:
                pass
        if found:
            break
        addr = ctypes.c_void_p(mbi.BaseAddress + mbi.RegionSize)
        if addr.value > 0x7FFFFFFF0000:
            break
    
    if not found:
        print('  Value not found in any private committed memory region')

print('\nDone')
