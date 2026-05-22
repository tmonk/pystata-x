"""Read gws structure on Windows to find all field offsets."""
import ctypes
import struct

dll_path = r'C:\Program Files\StataNow19\se-64.dll'
dll = ctypes.WinDLL(dll_path)
handle = dll._handle

_Main = dll.StataSO_Main
_Main.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_char_p)]
_Main.restype = ctypes.c_int
_Main(2, (ctypes.c_char_p * 2)(b'stata', b'-q'))
_Execute = dll.StataSO_Execute
_Execute.argtypes = [ctypes.c_char_p]
_Execute.restype = ctypes.c_int

# Find .data section
with open(dll_path, 'rb') as f:
    pe_data = f.read()
e_lfanew = struct.unpack('<I', pe_data[0x3c:0x40])[0]
opt_hdr_size = struct.unpack('<H', pe_data[e_lfanew+20:e_lfanew+22])[0]
sh_off = e_lfanew + 24 + opt_hdr_size
data_rva = 0
for i in range(struct.unpack('<H', pe_data[e_lfanew+6:e_lfanew+8])[0]):
    sh = pe_data[sh_off+i*40:sh_off+i*40+40]
    if sh[:8].rstrip(b'\x00').decode('utf-8', errors='replace') == '.data':
        data_rva = struct.unpack('<I', sh[12:16])[0]
        break

gws_ptr = handle + data_rva + 0x211644 - 0x68

def read_gws_fields(label):
    """Read all int32 gws fields and print interesting values."""
    interesting = []
    for off in range(0, 256, 4):
        buf = (ctypes.c_int * 1)()
        ctypes.memmove(buf, ctypes.c_void_p(gws_ptr + off), 4)
        val = buf[0]
        if 0 < val < 200000:
            interesting.append((off, val))
    print('  %s:' % label)
    for off, val in interesting:
        print('    gws+0x%02x = %d' % (off, val))

# Load auto
_Execute(b'sysuse auto, clear')
read_gws_fields('auto (nvar=12, nobs=74)')

# Load bpwide
_Execute(b'sysuse bpwide, clear')
read_gws_fields('bpwide (nvar=5, nobs=36)')

print('\nDone')
