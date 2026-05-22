"""Find data buffer pointer on Windows by searching gws vicinity."""
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

# Create clean dataset
dll.StataSO_Execute(b'clear')
dll.StataSO_Execute(b'set obs 1')
sentinel_val = 12345.6789
dll.StataSO_Execute(b'gen double __px_sentinel = ' + str(sentinel_val).encode())

# Find .data section
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

# Confirmed: sentinel is at data+0x922c00
SENTINEL_DATA_OFF = 0x922c00
sentinel_abs_addr = data_ptr + SENTINEL_DATA_OFF
print('sentinel abs:', hex(sentinel_abs_addr))

# gws vicinity
gws_off = 0x211644 - 0x68  # 0x2115DC
print('gws off:', hex(gws_off))

# Read a region around gws for pointer search
gws_read_start = 0x210000
gws_read_size = 0x8000  # 32KB
buf = (ctypes.c_char * gws_read_size)()
ctypes.memmove(buf, ctypes.c_void_p(data_ptr + gws_read_start), gws_read_size)
raw = bytes(buf)

sentinel_region_start = data_ptr + 0x920000
sentinel_region_end = data_ptr + 0x930000

print('\nSearching gws vicinity for pointers to data buffer region...')
for j in range(0, len(raw) - 8, 8):
    ptr = struct.unpack('<Q', raw[j:j+8])[0]
    if sentinel_region_start <= ptr <= sentinel_region_end:
        abs_off = gws_read_start + j
        print('  GWS_VICINITY+%x (abs %x): ptr=%x (data+%x)' 
              % (abs_off, data_ptr + abs_off, ptr, ptr - data_ptr))

# Also scan a region before, during, and after sentinel for data struct pointers
# Store the sentinel's actual position in each stride
# The data buffer has 1 variable, 1 obs = 8 bytes
# Check what's around the sentinel in memory
print('\nReading the data buffer region...')
db_buf = (ctypes.c_char * 2048)()
ctypes.memmove(db_buf, ctypes.c_void_p(data_ptr + SENTINEL_DATA_OFF - 1024), 2048)
db_raw = bytes(db_buf)

# Find the sentinel within this buffer
idx = db_raw.find(struct.pack('<d', sentinel_val))
print('Sentinel found at local offset %d (from page -1024)' % idx)

# Show surrounding qwords
for k in range(max(0, idx - 32), min(len(db_raw) - 8, idx + 64), 8):
    val = struct.unpack('<d', db_raw[k:k+8])[0]
    val_int = struct.unpack('<Q', db_raw[k:k+8])[0]
    marker = ' <-- SENTINEL' if k == idx else ''
    print('  [%+d] double=%.1f hex=%x%s' % (k - 1024, val, val_int, marker))

print('\nDone')
