"""Find Stata data buffer pointer on Windows using sentinel values."""
import ctypes
import struct

dll_path = r'C:\Program Files\StataNow19\se-64.dll'
dll = ctypes.WinDLL(dll_path)
handle = dll._handle

# Init Stata
dll.StataSO_Main.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_char_p)]
dll.StataSO_Main.restype = ctypes.c_int
dll.StataSO_Main(2, (ctypes.c_char_p * 2)(b'stata', b'-q'))

dll.StataSO_Execute.argtypes = [ctypes.c_char_p]
dll.StataSO_Execute.restype = ctypes.c_int

# Load dataset
dll.StataSO_Execute(b'sysuse auto, clear')

# Find .data section
with open(dll_path, 'rb') as f:
    pe_data = f.read()
e_lfanew = struct.unpack('<I', pe_data[0x3c:0x40])[0]
opt_hdr_size = struct.unpack('<H', pe_data[e_lfanew+20:e_lfanew+22])[0]
sh_off = e_lfanew + 24 + opt_hdr_size
data_rva = 0
data_size = 0
for i in range(struct.unpack('<H', pe_data[e_lfanew+6:e_lfanew+8])[0]):
    sh = pe_data[sh_off+i*40:sh_off+i*40+40]
    name = sh[:8].rstrip(b'\x00').decode('utf-8', errors='replace')
    if name == '.data':
        data_rva = struct.unpack('<I', sh[12:16])[0]
        data_vsize = struct.unpack('<I', sh[8:12])[0]
        data_rawsize = struct.unpack('<I', sh[16:20])[0]
        data_size = min(data_vsize, data_rawsize)
        break

data_ptr = handle + data_rva
# Read data section from loaded DLL using virtual size (not raw file size)
# Rescan to get correct virtual size
for k in range(struct.unpack('<H', pe_data[e_lfanew+6:e_lfanew+8])[0]):
    sk = pe_data[sh_off + k*40:sh_off + k*40 + 40]
    if sk[:8].rstrip(b'\x00').decode('utf-8', errors='replace') == '.data':
        data_vsize_from_pe = struct.unpack('<I', sk[8:12])[0]
        break
else:
    data_vsize_from_pe = data_size
data_size = data_vsize_from_pe  # Full virtual size in memory
print('Data section: addr=%x vsize=%d rawsize=%d' % (data_ptr, data_size, data_rawsize))

# Read the full data section from memory
data_buf = (ctypes.c_char * data_size)()
ctypes.memmove(data_buf, ctypes.c_void_p(data_ptr), data_size)
raw = bytes(data_buf)
print('Read %d bytes from .data' % len(raw))

# Step 1: Create a sentinel variable with unique value
sentinel_val = 12345.6789
sentinel_bytes = struct.pack('<d', sentinel_val)
print('Sentinel IEEE754 bytes:', sentinel_bytes.hex())

# Create the variable
dll.StataSO_Execute(b'gen double __px_sentinel = ' + str(sentinel_val).encode())
print('Created __px_sentinel')

# Read nvar to know which variable is our sentinel
nv_buf = (ctypes.c_int * 1)()
ctypes.memmove(nv_buf, ctypes.c_void_p(data_ptr + 0x211644), 4)
nvar = nv_buf[0]
print('Current nvar:', nvar)

# __px_sentinel is the last variable (index = nvar)
# We need to find the data buffer address
# The data buffer stores all values in a contiguous block

# Strategy 1: Scan gws struct for data buffer pointer
# gws at data_ptr + 0x211644 - 0x68 = data_ptr + 0x2115DC
gws_ptr = data_ptr + 0x211644 - 0x68
print('\ngws at:', hex(gws_ptr))

# The data buffer pointer could be at various offsets in gws
# On Linux, gws.D is at offset 0x48
# Let's read pointer values in gws and try them
count = 0
sentinel_match = None
for gws_off in range(0, 256, 8):
    ptr = struct.unpack('<Q', raw[gws_ptr - data_ptr + gws_off:gws_ptr - data_ptr + gws_off + 8])[0]
    if ptr < 0x10000:
        continue
    try:
        test_buf = (ctypes.c_double * 1)()
        ctypes.memmove(test_buf, ctypes.c_void_p(ptr), 8)
        if abs(test_buf[0] - sentinel_val) < 0.0001:
            print('Found sentinel via gws+%x: ptr=%x val=%f' % (gws_off, ptr, test_buf[0]))
            sentinel_match = (gws_off, ptr)
            count += 1
    except:
        pass

print('Sentinel matches found: %d' % count)

if sentinel_match:
    off, data_buffer = sentinel_match
    print('Data buffer pointer at .data+%x = %x' % (off, data_buffer))
    
    # The data buffer stores variables in order
    # Each observation has a fixed stride
    # Price is variable 1 (0-indexed) in auto dataset
    # Read price for observation 0
    
    # Read price at obs 0 (value should be 4099)
    price_buf = (ctypes.c_double * 1)()
    # The data layout: each obs has nvar double values
    # price is at position 0 in auto (variable index 0)
    obs_size = nvar * 8  # each double is 8 bytes
    price_offset = 0  # first variable = price
    ctypes.memmove(price_buf, ctypes.c_void_p(data_buffer + price_offset * 8), 8)
    print('Price[0] (expected 4099):', price_buf[0])
    
    # Also read mpg at obs 0 (variable index 1)
    mpg_buf = (ctypes.c_double * 1)()
    ctypes.memmove(mpg_buf, ctypes.c_void_p(data_buffer + 1 * 8), 8)
    print('MPG[0] (expected 22):', mpg_buf[0])

print('Done')
