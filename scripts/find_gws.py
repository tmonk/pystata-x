"""Find gws pointer near nvar offset in .data section."""
import ctypes
import struct

dll_path = r'C:\Program Files\StataNow19\se-64.dll'
dll = ctypes.WinDLL(dll_path)
handle = dll._handle

# Init Stata
_Main = dll.StataSO_Main
_Main.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_char_p)]
_Main.restype = ctypes.c_int
_Main(2, (ctypes.c_char_p * 2)(b'stata', b'-q'))
_Execute = dll.StataSO_Execute
_Execute.argtypes = [ctypes.c_char_p]
_Execute.restype = ctypes.c_int
_Execute(b'sysuse auto, clear')

# Find .data section
with open(dll_path, 'rb') as f:
    pe_data = f.read()
e_lfanew = struct.unpack('<I', pe_data[0x3c:0x40])[0]
pe = pe_data[e_lfanew:e_lfanew+0x200]
num_sections = struct.unpack('<H', pe[6:8])[0]
opt_hdr_size = struct.unpack('<H', pe[20:22])[0]
sh_off = e_lfanew + 24 + opt_hdr_size

for i in range(num_sections):
    sh = pe_data[sh_off+i*40:sh_off+i*40+40]
    name = sh[:8].rstrip(b'\x00').decode('utf-8', errors='replace')
    if name == '.data':
        data_rva = struct.unpack('<I', sh[12:16])[0]
        data_vsize = struct.unpack('<I', sh[8:12])[0]
        data_rawsize = struct.unpack('<I', sh[16:20])[0]
        data_ptr = handle + data_rva
        data_size = min(data_vsize, data_rawsize) if data_vsize else data_rawsize
        break

buf = (ctypes.c_char * data_size)()
ctypes.memmove(buf, ctypes.c_void_p(data_ptr), data_size)
raw = bytes(buf)

print('Data section at %x, size %d' % (data_ptr, data_size))

# Read pointers around nvar offset
nvar_off = 0x211644
print('GWS pointers near nvar offset %x:' % nvar_off)
for delta in range(-128, 128, 8):
    off = nvar_off + delta
    if off < 0 or off + 8 > len(raw):
        continue
    ptr = struct.unpack('<Q', raw[off:off+8])[0]
    if 0x10000 < ptr < 0x200000000:
        print('  delta=%+4d offset=%x ptr=%x' % (delta, off, ptr))

# Now also look for the data buffer
# Create a variable and fill it with a known value
_Execute(b'gen double __px_test = 999.99 in 1')
# Now search for 999.99 in memory - it must be in the Stata data buffer

# Actually, let's try a different approach:
# Change nvar to another dataset and see what else changes
_Execute(b'sysuse auto, clear')
# Scan raw data for the gws pointer at the nvar candidate
# gws = nvar_addr - offset_of_nvar_in_gws
# On Linux, gws.nvar at +0x68
# Let's try various offsets
gws_off = nvar_off
for assumed_nvar_offset_in_gws in [0x68, 0x60, 0x70, 0x54, 0x5c, 0x64, 0x6c, 0x58, 0x50, 0x4c, 0x44, 0x40]:
    # Assume gws + assumed_offset = &nvar
    gws = data_ptr + nvar_off - assumed_nvar_offset_in_gws
    # Verify by reading nvar from this gws
    try:
        read_buf = (ctypes.c_int * 1)()
        ctypes.memmove(read_buf, ctypes.c_void_p(gws + assumed_nvar_offset_in_gws), 4)
        if read_buf[0] == 12:  # auto has nvar=12
            print('Possible gws at %x: nvar at +%x = %d' % (gws, assumed_nvar_offset_in_gws, read_buf[0]))
            # Check nobs nearby
            for no_off in [assumed_nvar_offset_in_gws - 8, assumed_nvar_offset_in_gws + 8,
                           assumed_nvar_offset_in_gws - 4, assumed_nvar_offset_in_gws + 4,
                           assumed_nvar_offset_in_gws - 12, assumed_nvar_offset_in_gws + 12]:
                nobs_buf = (ctypes.c_int * 1)()
                ctypes.memmove(nobs_buf, ctypes.c_void_p(gws + no_off), 4)
                if nobs_buf[0] == 74:
                    print('  -> nobs at +%x = %d' % (no_off, nobs_buf[0]))
    except:
        pass

print('Done')
