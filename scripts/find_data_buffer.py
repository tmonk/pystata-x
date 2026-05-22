"""Test if hi32 values in gws struct are 32-bit addresses.
These could be data buffer pointers truncated to 32 bits."""
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
    if sh[:8].rstrip(b'\x00').decode('utf-8', errors='replace') == '.data':
        data_rva = struct.unpack('<I', sh[12:16])[0]
        break
data_ptr = handle + data_rva

# Create dataset with known value (not in .data, i.e., large enough)
dll.StataSO_Execute(b'clear')
dll.StataSO_Execute(b'set obs 100')
test_val = 88888.99999
dll.StataSO_Execute(b'gen double __px = ' + str(test_val).encode())
s_bytes = struct.pack('<d', test_val)

# Verify NOT in .data
found_in_data = False
for cs in range(0, 12*1024*1024, 256*1024):
    cur = min(256*1024, 12*1024*1024 - cs)
    try:
        buf = (ctypes.c_char * cur)()
        ctypes.memmove(buf, ctypes.c_void_p(data_ptr + cs), cur)
        if s_bytes in bytes(buf):
            found_in_data = True
            break
    except:
        break

# Read gws struct
gws_ptr = data_ptr + 0x211644 - 0x68
gws_off = gws_ptr - data_ptr
region_start = max(0, gws_off - 512)
buf = (ctypes.c_char * 4096)()
ctypes.memmove(buf, ctypes.c_void_p(data_ptr + region_start), 4096)
raw = bytes(buf)
gws_rel = gws_off - region_start

if found_in_data:
    print('Value IN .data - buffer is in .data section')
else:
    print('Value NOT in .data - buffer is on heap')
    print('\nTesting hi32 values at gws+0x5C, 0x6C, 0x74, 0x7C as addresses...')
    
    # Check each hi32 field as a 32-bit pointer
    fields = [(0x58, 'gws+0x58 hi32'), (0x5C, 'gws+0x5C field'), 
              (0x68, 'gws+0x68/hi(gws+0x6C)'), (0x6C, 'gws+0x6C'),
              (0x70, 'gws+0x70'), (0x74, 'gws+0x74'),
              (0x78, 'gws+0x78'), (0x7C, 'gws+0x7C'),
              (0x80, 'gws+0x80'), (0x84, 'gws+0x84')]
    
    for off, desc in fields:
        abs_off = region_start + gws_rel + off
        if abs_off + 4 > len(raw):
            continue
        val32 = struct.unpack('<I', raw[abs_off:abs_off+4])[0]
        # Try as a 32-bit address (zero-extend to 64-bit)
        if val32 > 0x10000:  # Looks like a pointer
            ptr64 = val32  # Zero-extend (upper 32 bits = 0)
            try:
                test_buf = (ctypes.c_double * 5)()
                ctypes.memmove(test_buf, ctypes.c_void_p(ptr64), 40)
                for k in range(5):
                    if abs(test_buf[k] - test_val) < 0.0001:
                        print('  %s: val32=%x -> ptr=%x CONTAINS SENTINEL at slot %d!' 
                              % (desc, val32, ptr64, k))
                        break
                else:
                    # Check if any value in the first 5 is a valid double
                    for k in range(5):
                        if test_buf[k] != 0:
                            pass  # has non-zero data
            except:
                pass
        # Also try as DLL-relative (handle + val32)
        if val32 < 0x04000000:  # Could be DLL RVA
            ptr64 = handle + val32
            try:
                test_buf = (ctypes.c_double * 5)()
                ctypes.memmove(test_buf, ctypes.c_void_p(ptr64), 40)
                for k in range(5):
                    if abs(test_buf[k] - test_val) < 0.0001:
                        print('  %s: RVA=%x -> ptr=%x CONTAINS SENTINEL at slot %d!' 
                              % (desc, val32, ptr64, k))
                        break
            except:
                pass
    
    # Also check: what if hi32 + lo32 = a full 64-bit address?
    # E.g., gws+0x68 = combined as lo32=nvar, hi32=hi
    # But this would need TWO fields: low and high parts
    # Check: gws+0x6C (hi) as pointer = 0, gws+0x70 as lo = 0x1b9
    # Try combining gws+0x6C and gws+0x70 as a 64-bit address
    print('\nTrying hi32+lo32 combinations as 64-bit addresses...')
    for lo_off, hi_off in [(0x6C, 0x70), (0x68, 0x6C), (0x78, 0x7C), (0x74, 0x78)]:
        lo_abs = gws_rel + lo_off
        hi_abs = gws_rel + hi_off
        lo32 = struct.unpack('<I', raw[lo_abs:lo_abs+4])[0] if lo_abs + 4 <= len(raw) else 0
        hi32 = struct.unpack('<I', raw[hi_abs:hi_abs+4])[0] if hi_abs + 4 <= len(raw) else 0
        # Try both byte orders
        for ptr in [(hi32 << 32) | lo32, (lo32 << 32) | hi32]:
            if ptr < 0x10000 or ptr > 0x7FFFFFFFFFFF:
                continue
            try:
                test_buf = (ctypes.c_double * 5)()
                ctypes.memmove(test_buf, ctypes.c_void_p(ptr), 40)
                for k in range(5):
                    if abs(test_buf[k] - test_val) < 0.0001:
                        print('  gws+%x+%x combined=%x CONTAINS SENTINEL at slot %d!' 
                              % (lo_off, hi_off, ptr, k))
                        break
            except:
                pass

print('\nDone')
