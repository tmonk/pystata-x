"""Understand data buffer layout on Windows.
Sentinel is at data+0x922C00 for tiny datasets. Find it for larger ones."""
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
gws_off = 0x211644 - 0x68  # 0x2115DC

def find_sentinel_in_data(dll, data_ptr, data_vsize, sentinel_val):
    s_bytes = struct.pack('<d', sentinel_val)
    chunk_size = 256 * 1024
    for chunk_start in range(0, data_vsize, chunk_size):
        cur_size = min(chunk_size, data_vsize - chunk_start)
        buf = (ctypes.c_char * cur_size)()
        try:
            ctypes.memmove(buf, ctypes.c_void_p(data_ptr + chunk_start), cur_size)
        except:
            return None
        chunk_raw = bytes(buf)
        idx = chunk_raw.find(s_bytes)
        if idx >= 0:
            return chunk_start + idx
    return None

def search_gws_for_val(dll, data_ptr, data_vsize, gws_off, target_val, search_radius=65536):
    """Search vicinity of gws for a pointer containing target_val."""
    read_start = max(0, gws_off - search_radius)
    read_size = min(data_vsize - read_start, search_radius * 2)
    buf = (ctypes.c_char * read_size)()
    ctypes.memmove(buf, ctypes.c_void_p(data_ptr + read_start), read_size)
    raw = bytes(buf)
    matches = []
    for j in range(0, len(raw) - 8, 8):
        ptr = struct.unpack('<Q', raw[j:j+8])[0]
        if ptr < 0x10000 or ptr > 0x7FFFFFFFFFFF:
            continue
        if handle <= ptr < handle + 0x04000000:
            continue
        try:
            test_buf = (ctypes.c_double * 1)()
            ctypes.memmove(test_buf, ctypes.c_void_p(ptr), 8)
            if abs(test_buf[0] - target_val) < 0.0001:
                abs_off = read_start + j
                matches.append((abs_off, ptr))
        except:
            pass
    return matches

# Test 1: tiny dataset
print('\n=== Test 1: 1 var, 1 obs ===')
dll.StataSO_Execute(b'clear')
dll.StataSO_Execute(b'set obs 1')
dll.StataSO_Execute(b'gen double __px_a = 12345.6789')
off1 = find_sentinel_in_data(dll, data_ptr, data_vsize, 12345.6789)
print('  data+%s (1 obs)' % ('None' if off1 is None else hex(off1)))

# Test 2: medium dataset
print('\n=== Test 2: 3 vars, 2 obs ===')
dll.StataSO_Execute(b'clear')
dll.StataSO_Execute(b'set obs 2')
dll.StataSO_Execute(b'gen double __px_a = 1111.2222')
dll.StataSO_Execute(b'gen double __px_b = 3333.4444')
dll.StataSO_Execute(b'gen double __px_c = 5555.6666')
for label, val in [('a', 1111.2222), ('b', 3333.4444), ('c', 5555.6666)]:
    off = find_sentinel_in_data(dll, data_ptr, data_vsize, val)
    if off is not None:
        print('  __px_%s at data+%s (IN .data)' % (label, hex(off)))
    else:
        print('  __px_%s NOT in .data (must be in heap)' % label)
        matches = search_gws_for_val(dll, data_ptr, data_vsize, gws_off, val)
        if matches:
            for moff, mptr in matches:
                print('    Found via gws_vic+%x -> ptr=%x' % (moff, mptr))
        else:
            print('    Not found via gws vicinity either')

# Test 3: larger dataset
print('\n=== Test 3: 12 vars, 74 obs (auto) ===')
dll.StataSO_Execute(b'clear')
dll.StataSO_Execute(b'sysuse auto, clear')
nv_buf = (ctypes.c_int * 1)()
ctypes.memmove(nv_buf, ctypes.c_void_p(data_ptr + 0x211644), 4)
print('  nvar:', nv_buf[0])

# Find price (first obs, first var = 4099)
off = find_sentinel_in_data(dll, data_ptr, data_vsize, 4099.0)
if off is not None:
    print('  price(obs0) at data+%s (IN .data)' % hex(off))
else:
    print('  price(obs0) NOT in .data (must be in heap)')
    matches = search_gws_for_val(dll, data_ptr, data_vsize, gws_off, 4099.0)
    if matches:
        for moff, mptr in matches[:5]:
            print('    Found via gws_vic+%x -> ptr=%x' % (moff, mptr))
    else:
        print('    Not found via gws vicinity either')

# Test 4: huge search - find the data buffer by searching ALL .data for heap pointers
print('\n=== Test 4: Search ALL .data section for heap ptrs to var values ===')
dll.StataSO_Execute(b'clear')
dll.StataSO_Execute(b'sysuse auto, clear')
# Use a unique value
dll.StataSO_Execute(b'gen double __px_unique = 888888.9999')
test_val = 888888.9999

# Check if in .data
off = find_sentinel_in_data(dll, data_ptr, data_vsize, test_val)
print('  __px_unique in .data:', off is not None, 'at' if off else '', hex(off) if off else '')
if off is None:
    # It's in heap. Find the data buffer pointer.
    print('  Searching gws vicinity for the pointer...')
    matches = search_gws_for_val(dll, data_ptr, data_vsize, gws_off, test_val, 65536*4)
    if matches:
        for moff, mptr in matches:
            print('    FOUND at .data+%x: ptr=%x' % (moff, mptr))
            print('    RVA:', hex(mptr - handle))
    else:
        print('  NOT found in gws vicinity. Trying FULL .data scan...')
        # Full scan of .data for heap pointers
        s_bytes = struct.pack('<d', test_val)
        count = 0
        for chunk_start in range(0, data_vsize, 65536):
            cur = min(65536, data_vsize - chunk_start)
            buf = (ctypes.c_char * cur)()
            try:
                ctypes.memmove(buf, ctypes.c_void_p(data_ptr + chunk_start), cur)
            except:
                continue
            raw = bytes(buf)
            for j in range(0, len(raw) - 8, 8):
                ptr = struct.unpack('<Q', raw[j:j+8])[0]
                if ptr < 0x10000 or ptr > 0x7FFFFFFFFFFF:
                    continue
                if handle <= ptr < handle + 0x04000000:
                    continue
                try:
                    test_buf = (ctypes.c_double * 1)()
                    ctypes.memmove(test_buf, ctypes.c_void_p(ptr), 8)
                    if abs(test_buf[0] - test_val) < 0.0001:
                        print('    FOUND at .data+%x: ptr=%x (RVA: %x)' 
                              % (chunk_start + j, ptr, ptr - handle))
                        count += 1
                        if count >= 3:
                            break
                except:
                    pass
            if count >= 3:
                break
        print('  Total matches:', count)

print('\nDone')
