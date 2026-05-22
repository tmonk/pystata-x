"""Read gws struct and nearby memory systematically to find data buffer pointer."""
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

# Load a dataset
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
print('data_ptr:', hex(data_ptr))
data_rva_actual = data_rva  # For computing RVA offsets

# nvar at data_ptr + 0x211644
nv_buf = (ctypes.c_int * 1)()
ctypes.memmove(nv_buf, ctypes.c_void_p(data_ptr + 0x211644), 4)
nvar_val = nv_buf[0]
print('nvar:', nvar_val)

# gws at data_ptr + 0x2115DC
gws_ptr = data_ptr + 0x211644 - 0x68
gws_off = gws_ptr - data_ptr

# Read 8192 bytes starting from 512 bytes BEFORE gws
# This gives us a clear picture of the gws structure
region_start = gws_off - 512
region_size = 8192
print('\nReading gws region 0x%x-0x%x (relative to data)' % (region_start, region_start + region_size))
buf = (ctypes.c_char * region_size)()
ctypes.memmove(buf, ctypes.c_void_p(data_ptr + region_start), region_size)
raw = bytes(buf)

# Analyze 8-byte fields near gws
# gws is at offset 512 within our read buffer
gws_rel = 512  # offset of gws start in our buffer
print('\n=== gws fields (relative to gws start) ===')
print('Off in gws | Abs data off | Value (hex) | Value (int) | Notes')
print('-' * 80)

for off in range(0, min(region_size - gws_rel, 2048), 8):
    abs_off = region_start + gws_rel + off
    val = struct.unpack('<Q', raw[gws_rel + off:gws_rel + off + 8])[0]
    notes = ''
    
    # Check if it's nvar (should be at gws+0x68)
    if off == 0x68:
        notes = 'nvar=' + str(val)
    elif off == 0:
        notes = 'gws start'
    # Check if it's a pointer within the DLL
    elif handle <= val < handle + 0x04000000:
        rva = val - handle
        notes = 'DLL ptr -> rva %x' % rva
    elif val < 1000000 and val > 0:
        notes = 'small int'
    
    if notes:
        print('gws+%-4d | data+%-9x | %-16x | %-10d | %s' % (off, abs_off, val, val, notes))

# Now specifically look for the data buffer pointer
# The data buffer for auto (12 vars, 74 obs) is 74 * 12 * 8 = 7104 bytes
# Find it by looking at ALL qwords in gws vicinity that point to heap memory
print('\n=== All pointers in gws region pointing OUTSIDE DLL ===')
count = 0
for j in range(0, region_size - 8, 8):
    ptr = struct.unpack('<Q', raw[j:j+8])[0]
    if ptr < 0x10000 or ptr > 0x7FFFFFFFFFFF:
        continue
    if handle <= ptr < handle + 0x04000000:
        continue  # DLL-local pointer
    abs_off = region_start + j
    gws_rel_off = abs_off - (region_start + 512)
    # Try reading the first double at this pointer
    try:
        test_buf = (ctypes.c_double * 1)()
        ctypes.memmove(test_buf, ctypes.c_void_p(ptr), 8)
        val = test_buf[0]
        print('  data+%x (gws%+d): ptr=%x first_val=%.1f' % (abs_off, gws_rel_off, ptr, val))
        count += 1
    except:
        pass
    if count >= 50:
        print('  ... (showing 50)')
        break

if count == 0:
    print('  (none found in this region)')
    print('\nTrying alternative: maybe data buffer is stored at gws+0x48 (Linux convention)')
    linux_off = 0x48
    linux_ptr = struct.unpack('<Q', raw[gws_rel + linux_off:gws_rel + linux_off + 8])[0]
    print('  gws+0x48 value: %x' % linux_ptr)
    if handle <= linux_ptr < handle + 0x04000000:
        # Try dereferencing this DLL-local pointer
        print('  Is a DLL-local pointer. Data at that address:')
        for k in range(8):
            v = struct.unpack('<Q', raw[gws_rel + k*8:gws_rel + k*8 + 8])[0]
            print('    [%d] %x' % (k, v))

# Also check: maybe the data buffer is at a computed RVA
# On Linux, gws.D = gws + 0x48 = pointer to data buffer
# The VALUE at gws+0x48 on Linux is a HEAP pointer
# Let me check what's at gws+0x48 on Windows
print('\n=== Detailed gws dump (0-256 bytes) ===')
for off in range(0, 256, 8):
    abs_off = region_start + gws_rel + off
    val = struct.unpack('<Q', raw[gws_rel + off:gws_rel + off + 8])[0]
    val_d = struct.unpack('<d', raw[gws_rel + off:gws_rel + off + 8])[0]
    line = 'gws+%03d: 0x%016x (int=%-12d double=%.2f' % (off, val, val, val_d)
    # Type check
    if handle <= val < handle + 0x04000000:
        line += ' [DLL ptr RVA %x]' % (val - handle)
    elif 1 <= val < 1000000:
        line += ' [small int]'
    elif val >= 0x10000:
        line += ' [heap ptr?]'
    line += ')'
    print(line)

print('\nDone')
