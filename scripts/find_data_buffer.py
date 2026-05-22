"""Find Stata data buffer pointer on Windows using a clean dataset."""
import ctypes
import struct
import binascii

dll_path = r'C:\Program Files\StataNow19\se-64.dll'
dll = ctypes.WinDLL(dll_path)
handle = dll._handle
print('DLL handle:', hex(handle))

# Init Stata
dll.StataSO_Main.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_char_p)]
dll.StataSO_Main.restype = ctypes.c_int
dll.StataSO_Main(2, (ctypes.c_char_p * 2)(b'stata', b'-q'))

dll.StataSO_Execute.argtypes = [ctypes.c_char_p]
dll.StataSO_Execute.restype = ctypes.c_int

# Find .data section
with open(dll_path, 'rb') as f:
    pe_data = f.read()
e_lfanew = struct.unpack('<I', pe_data[0x3c:0x40])[0]
opt_hdr_size = struct.unpack('<H', pe_data[e_lfanew+20:e_lfanew+22])[0]
sh_off = e_lfanew + 24 + opt_hdr_size
num_sections = struct.unpack('<H', pe_data[e_lfanew+6:e_lfanew+8])[0]

data_rva = 0
data_vsize = 0
for i in range(num_sections):
    sh = pe_data[sh_off + i*40:sh_off + i*40 + 40]
    name = sh[:8].rstrip(b'\x00').decode('utf-8', errors='replace')
    if name == '.data':
        data_rva = struct.unpack('<I', sh[12:16])[0]
        data_vsize = struct.unpack('<I', sh[8:12])[0]
        break

data_ptr = handle + data_rva
print('Data section rva=%x ptr=%x vsize=%d' % (data_rva, data_ptr, data_vsize))

# Step 1: Create a clean dataset with a single variable and sentinel value
print('\nCreating clean dataset...')
dll.StataSO_Execute(b'clear')
dll.StataSO_Execute(b'set obs 1')
sentinel_val = 12345.6789
dll.StataSO_Execute(b'gen double __px_sentinel = ' + str(sentinel_val).encode())

# Verify nvar
nv_buf = (ctypes.c_int * 1)()
ctypes.memmove(nv_buf, ctypes.c_void_p(data_ptr + 0x211644), 4)
nvar = nv_buf[0]
print('nvar:', nvar)
assert nvar >= 1, 'nvar should be >= 1'

sentinel_bytes = struct.pack('<d', sentinel_val)
print('Sentinel bytes:', sentinel_bytes.hex())

# Step 2: Read the .data section in chunks and search for the sentinel
print('\nSearching .data section for sentinel (this may take a moment)...')
found_offset = None
chunk_size = 1024 * 1024  # 1MB chunks
for chunk_start in range(0, data_vsize, chunk_size):
    cur_chunk_size = min(chunk_size, data_vsize - chunk_start)
    buf = (ctypes.c_char * cur_chunk_size)()
    ctypes.memmove(buf, ctypes.c_void_p(data_ptr + chunk_start), cur_chunk_size)
    chunk_raw = bytes(buf)
    idx = chunk_raw.find(sentinel_bytes)
    if idx >= 0:
        found_offset = chunk_start + idx
        print('Found sentinel at .data+%x (%d)' % (found_offset, found_offset))
        break

if found_offset is None:
    print('Sentinel NOT in .data section — must be in heap memory.')
    # The data buffer is heap-allocated. Search gws region for pointers.
    
# Step 3: Find gws and scan surrounding memory for the data buffer pointer
gws_ptr = data_ptr + 0x211644 - 0x68  # nvar is at gws+0x68
print('\ngws at:', hex(gws_ptr))
gws_off = gws_ptr - data_ptr

# Read a larger region around gws (maybe 4KB)
region_start = max(0, gws_off - 0x2000)
region_size = min(data_vsize - region_start, 0x10000)  # 64KB around gws
buf = (ctypes.c_char * region_size)()
ctypes.memmove(buf, ctypes.c_void_p(data_ptr + region_start), region_size)
region_raw = bytes(buf)

# For each qword in region, check if it's a pointer that contains our sentinel
print('Scanning region 0x%x-0x%x for data buffer pointers...' % (region_start, region_start + region_size))
count = 0
for j in range(0, len(region_raw) - 8, 8):
    ptr = struct.unpack('<Q', region_raw[j:j+8])[0]
    # Skip obviously invalid pointers
    if ptr < 0x10000 or ptr > 0x7FFFFFFFFFFFFFFF:
        continue
    # Skip pointers into PE modules (DLL regions)
    if handle <= ptr < handle + 0x04000000:
        continue
    # Read a double at this pointer
    try:
        test_buf = (ctypes.c_double * 1)()
        ctypes.memmove(test_buf, ctypes.c_void_p(ptr), 8)
        if abs(test_buf[0] - sentinel_val) < 0.0001:
            abs_off = region_start + j
            gws_rel_off = abs_off - gws_off
            print('  FOUND at region+%x (gws%+x): ptr=%x val=%f' % (abs_off, gws_rel_off, ptr, test_buf[0]))
            count += 1
    except:
        pass

if count == 0:
    print('No direct pointer found in gws region. Trying larger scan...')
    # The data buffer might be stored 2 hops away.
    # Try scanning all qwords in the region, following each non-PE pointer
    # through one indirection level.
    print('Scanning region for indirect pointers (2-hop)...')
    for j in range(0, len(region_raw) - 8, 8):
        ptr1 = struct.unpack('<Q', region_raw[j:j+8])[0]
        if ptr1 < 0x10000 or ptr1 > 0x7FFFFFFFFFFFFFFF:
            continue
        if handle <= ptr1 < handle + 0x04000000:
            continue
        # Read 64 bytes at ptr1 (might be a data structure with another pointer)
        try:
            buf2 = (ctypes.c_char * 256)()
            ctypes.memmove(buf2, ctypes.c_void_p(ptr1), 256)
            raw2 = bytes(buf2)
            for k in range(0, 256 - 8, 8):
                ptr2 = struct.unpack('<Q', raw2[k:k+8])[0]
                if ptr2 < 0x10000 or ptr2 > 0x7FFFFFFFFFFFFFFF:
                    continue
                if handle <= ptr2 < handle + 0x04000000:
                    continue
                try:
                    test_buf = (ctypes.c_double * 1)()
                    ctypes.memmove(test_buf, ctypes.c_void_p(ptr2), 8)
                    if abs(test_buf[0] - sentinel_val) < 0.0001:
                        abs_off = region_start + j
                        gws_rel_off = abs_off - gws_off
                        print('  FOUND (2-hop) at region+%x (gws%+x): ptr1=%x ptr2=%x' 
                              % (abs_off, gws_rel_off, ptr1, ptr2))
                        count += 1
                        if count >= 5:
                            break
                except:
                    pass
            if count >= 5:
                break
        except:
            pass

print('\nTotal matches: %d' % count)
print('Done')
