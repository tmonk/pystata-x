"""Test: does 0x922C00 always hold the LAST variable created after clear?"""
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

def read_double_at(off):
    buf = (ctypes.c_double * 1)()
    ctypes.memmove(buf, ctypes.c_void_p(data_ptr + off), 8)
    return buf[0]

def read_int_at(off):
    buf = (ctypes.c_int * 1)()
    ctypes.memmove(buf, ctypes.c_void_p(data_ptr + off), 4)
    return buf[0]

# Test: create vars one at a time and check 0x922C00
print('=== Test 1: clear + 1 var + 1000 obs ===')
dll.StataSO_Execute(b'clear')
dll.StataSO_Execute(b'set obs 1000')
dll.StataSO_Execute(b'gen double x1 = 1111')
print('  nvar:', read_int_at(0x211644))
print('  scratch(0x922C00): %.0f' % read_double_at(0x922C00))

# After gen, x1's obs[0] should be at the data buffer
# Find 1111 in .data section
s_bytes = struct.pack('<d', 1111.0)
for cs in range(0, data_vsize, 256*1024):
    cur = min(256*1024, data_vsize - cs)
    try:
        buf = (ctypes.c_char * cur)()
        ctypes.memmove(buf, ctypes.c_void_p(data_ptr + cs), cur)
    except:
        continue
    idx = bytes(buf).find(s_bytes)
    if idx >= 0:
        print('  x1 value at data+%x' % (cs + idx))
        break

# Add second var
print('\n=== Test 2: add second var ===')
dll.StataSO_Execute(b'gen double x2 = 2222')
print('  nvar:', read_int_at(0x211644))
print('  scratch(0x922C00): %.0f' % read_double_at(0x922C00))
s_bytes = struct.pack('<d', 2222.0)
for cs in range(0, data_vsize, 256*1024):
    cur = min(256*1024, data_vsize - cs)
    try:
        buf = (ctypes.c_char * cur)()
        ctypes.memmove(buf, ctypes.c_void_p(data_ptr + cs), cur)
    except:
        continue
    idx = bytes(buf).find(s_bytes)
    if idx >= 0:
        print('  x2 value at data+%x' % (cs + idx))
        break
s_bytes = struct.pack('<d', 1111.0)
for cs in range(0, data_vsize, 256*1024):
    cur = min(256*1024, data_vsize - cs)
    try:
        buf = (ctypes.c_char * cur)()
        ctypes.memmove(buf, ctypes.c_void_p(data_ptr + cs), cur)
    except:
        continue
    if s_bytes in bytes(buf):
        print('  x1 value still in .data: YES')
        break
else:
    print('  x1 value no longer in .data')

# Add third var with different value for each obs
print('\n=== Test 3: third var with per-obs values ===')
dll.StataSO_Execute(b'gen double x3 = _n * 100')
print('  nvar:', read_int_at(0x211644))
print('  scratch(0x922C00): %.0f' % read_double_at(0x922C00))
s_bytes = struct.pack('<d', 100.0)  # obs 0 has value 100
for cs in range(0, data_vsize, 256*1024):
    cur = min(256*1024, data_vsize - cs)
    try:
        buf = (ctypes.c_char * cur)()
        ctypes.memmove(buf, ctypes.c_void_p(data_ptr + cs), cur)
    except:
        continue
    idx = bytes(buf).find(s_bytes)
    if idx >= 0:
        print('  x3(obs0)=100 at data+%x' % (cs + idx))
        break

# Now the key test: is the data buffer at 0x922C00 or elsewhere?
# Check: does the data buffer address change after adding more vars?
print('\n=== Test 4: Buffer location comparison ===')
print('  After 3 var+1000 obs:')
print('  scratch(0x922C00): %.0f' % read_double_at(0x922C00))

# Search for ALL values near 0x922C00 (maybe the data buffer starts before 0x922C00)
print('\n=== Reading extended area around 0x922C00 ===')
buf = (ctypes.c_double * 500)()
try:
    ctypes.memmove(buf, ctypes.c_void_p(data_ptr + 0x922C00 - 2000), 4000)
    non_zero = [(i, buf[i]) for i in range(500) if buf[i] != 0]
    print('Non-zero values in [0x922C00-2000, 0x922C00+2000]:')
    for idx, val in non_zero[:30]:
        print('  [+%d] %.0f' % (0x922C00 - 2000 + idx*8, val))
except:
    print('  (read error)')

# Try: the data buffer might be at a FIXED location from the DLL base
# that I haven't checked yet. Let me check the .bss section
print('\n=== Checking other sections ===')
for i in range(struct.unpack('<H', pe_data[e_lfanew+6:e_lfanew+8])[0]):
    sh = pe_data[sh_off + i*40:sh_off + i*40 + 40]
    name = sh[:8].rstrip(b'\x00').decode('utf-8', errors='replace')
    vrva = struct.unpack('<I', sh[12:16])[0]
    vsize = struct.unpack('<I', sh[8:12])[0]
    if name in ('.bss', '.data'):
        print('  %s: RVA=%x vsize=%d' % (name, vrva, vsize))
        if name == '.bss' and vsize > 0:
            # The .bss section exists virtually but not in the file
            # It's zero-initialized and can hold large buffers
            buf = (ctypes.c_char * 1)()
            try:
                ctypes.memmove(buf, ctypes.c_void_p(handle + vrva), 1)
                print('    .bss is readable at', hex(handle + vrva))
                # Check if 0x922C00 falls within .bss
                if vrva <= (data_rva + 0x922C00) < vrva + vsize:
                    print('    scratch buffer IS in .bss!')
                else:
                    print('    scratch buffer NOT in .bss')
            except:
                print('    .bss not directly readable')

print('\nDone')
