"""Extended gws analysis - read more of the struct to find data buffer pointer."""
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
dll.StataSO_Execute(b'sysuse auto, clear')

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

# nvar
nv_buf = (ctypes.c_int * 1)()
ctypes.memmove(nv_buf, ctypes.c_void_p(data_ptr + 0x211644), 4)
print('nvar:', nv_buf[0])

# gws: start at the assumed gws offset and read 8KB
gws_ptr = data_ptr + 0x211644 - 0x68
gws_off = gws_ptr - data_ptr
print('gws off:', hex(gws_off))

# Read 8KB from gws (4KB before to 4KB after)
region_start = max(0, gws_off - 4096)
region_size = 8192
buf = (ctypes.c_char * region_size)()
ctypes.memmove(buf, ctypes.c_void_p(data_ptr + region_start), region_size)
raw = bytes(buf)

gws_rel = gws_off - region_start  # offset of gws start in our buffer

print('\n=== gws fields (as 4-byte and 8-byte reads) ===')
print('Off in gws | Data+off | Qword (8-byte) | Lo32 (4-byte) | Hi32 (4-byte)')
print('-' * 80)

# Also track which values might be pointers
for off in range(0, min(len(raw) - gws_rel, 4096), 8):
    abs_off = region_start + gws_rel + off
    qword = struct.unpack('<Q', raw[gws_rel + off:gws_rel + off + 8])[0]
    lo32 = qword & 0xFFFFFFFF
    hi32 = (qword >> 32) & 0xFFFFFFFF
    
    notes = ''
    
    lo32_notes = ''
    hi32_notes = ''
    
    # Check lo32 as small int
    if lo32 < 200 and lo32 != 0:
        if off == 0x68:
            lo32_notes = ' (nvar!)'
        else:
            lo32_notes = ''
    
    # Check hi32 as small int  
    if hi32 < 200 and hi32 != 0:
        hi32_notes = ' (small int %d)' % hi32
    
    # Check if lo32 is a pointer (user space addr < 0x7FFFFFFF)
    if 0x10000 < lo32 < 0x7FFFFFFF:
        lo32_notes += ' [ptr?]'
    
    # Check if hi32 is a pointer
    if 0x10000 < hi32 < 0x7FFFFFFF:
        hi32_notes += ' [ptr?]'
    
    if lo32 != 0 or hi32 != 0:
        print('gws+%-4d | data+%-6x | %-18s | %-8x %s | %-8x %s' % 
              (off, abs_off, hex(qword), lo32, lo32_notes, hi32, hi32_notes))

# Now specifically look for the data buffer
# Create a known-value dataset and find it
print('\n=== Searching for data buffer via known values ===')
dll.StataSO_Execute(b'clear')
dll.StataSO_Execute(b'set obs 10')
dll.StataSO_Execute(b'gen double __px_a = 111111')
dll.StataSO_Execute(b'gen double __px_b = 222222')
dll.StataSO_Execute(b'gen double __px_c = 333333')

# First find these values in the data section
val_a = struct.pack('<d', 111111.0)
val_b = struct.pack('<d', 222222.0)
val_c = struct.pack('<d', 333333.0)

found_a = None
found_b = None
found_c = None

chunk_size = 256 * 1024
for chunk_start in range(0, data_vsize, chunk_size):
    cur = min(chunk_size, data_vsize - chunk_start)
    buf = (ctypes.c_char * cur)()
    try:
        ctypes.memmove(buf, ctypes.c_void_p(data_ptr + chunk_start), cur)
    except:
        continue
    raw_chunk = bytes(buf)
    if found_a is None:
        idx = raw_chunk.find(val_a)
        if idx >= 0: found_a = chunk_start + idx
    if found_b is None:
        idx = raw_chunk.find(val_b)
        if idx >= 0: found_b = chunk_start + idx
    if found_c is None:
        idx = raw_chunk.find(val_c)
        if idx >= 0: found_c = chunk_start + idx
    if found_a and found_b and found_c:
        break

print('Found: a=%s b=%s c=%s' % 
      (hex(found_a) if found_a else 'N', 
       hex(found_b) if found_b else 'N',
       hex(found_c) if found_c else 'N'))

if found_b and found_a:
    print('Data buffer stride (vars * obs?):', found_b - found_a)
    print('Obs count computed:', (found_b - found_a) // 8)

# Now search gws vicinity for pointers to where these values are
print('\n=== Search gws region for pointers to data buffer ===')
refound_a = data_ptr + found_a if found_a else 0
buf = (ctypes.c_char * data_vsize)()
try:
    ctypes.memmove(buf, ctypes.c_void_p(data_ptr), min(data_vsize, 4*1024*1024))
    full_raw = bytes(buf)
    print('Read first 4MB of .data section')
except:
    full_raw = b''
    print('Could not read full .data')

# Search for ptr_a in the data section
if found_a:
    ptr_a = refound_a
    ptr_a_rva = ptr_a - handle
    print('Looking for pointer to data buffer at abs %x / RVA %x' % (ptr_a, ptr_a_rva))
    
    # By absolute address 
    for off in range(0, len(full_raw) - 8, 8):
        val = struct.unpack('<Q', full_raw[off:off+8])[0]
        if val == ptr_a:
            print('  ABS PTR at .data+%x' % off)
        if val == ptr_a_rva:
            print('  RVA PTR at .data+%x' % off)
    
    # Also try 4-byte RVA
    for off in range(0, len(full_raw) - 4, 4):
        val32 = struct.unpack('<I', full_raw[off:off+4])[0]
        if val32 == (ptr_a_rva & 0xFFFFFFFF):
            print('  32-bit RVA at .data+%x' % off)
    
    # Also check: is the buffer at a known offset from nvar?
    # nvar is at data+0x211644. Data buffer should be at some computed location
    # Check if any gws field value = data buffer offset
    print('\nChecking if any gws field equals data section offset of buffer...')
    buf_size = min(data_vsize - region_start, 4 * 1024 * 1024)
    buf2 = (ctypes.c_char * buf_size)()
    ctypes.memmove(buf2, ctypes.c_void_p(data_ptr + region_start), buf_size)
    full_raw2 = bytes(buf2)
    
    # Count how many times ptr_a (abs) or any pointer within range appears as a qword
    ptr_a_page = ptr_a & ~0xFFF  # 4KB page containing data buffer
    count = 0
    for off in range(0, len(full_raw2) - 8, 8):
        val = struct.unpack('<Q', full_raw2[off:off+8])[0]
        if ptr_a_page <= val < ptr_a_page + 0x1000:
            print('  NEAR DATA PTR at region+%x (data+%x): val=%x' 
                  % (off, region_start + off, val))
            count += 1
            if count >= 5:
                break

print('\nDone')
