"""Debug pe_discover_memory_layout."""
import ctypes
import struct

dll_path = r'C:\Program Files\StataNow19\se-64.dll'

print('Loading DLL...', flush=True)
dll = ctypes.WinDLL(dll_path)
handle = dll._handle
print('Handle:', hex(handle), flush=True)

kernel32 = ctypes.windll.kernel32

print('Getting StataSO_Main...', flush=True)
_Main = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_char_p))
main_addr = kernel32.GetProcAddress(ctypes.c_void_p(handle), b'StataSO_Main')
print('StataSO_Main addr:', hex(main_addr) if main_addr else 'None', flush=True)

print('Initializing Stata...', flush=True)
argv = (ctypes.c_char_p * 2)(b'stata', b'-q')
rc = _Main(ctypes.c_void_p(main_addr & 0xffffffff).value)(2, argv)
print('Init rc:', rc, flush=True)

print('Getting StataSO_Execute...', flush=True)
_Execute = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_char_p)
exec_addr = kernel32.GetProcAddress(ctypes.c_void_p(handle), b'StataSO_Execute')
print('Exec addr:', hex(exec_addr) if exec_addr else 'None', flush=True)

stata_exec = _Execute(exec_addr)
print('Loading auto dataset...', flush=True)
rc = stata_exec(b'sysuse auto, clear')
print('Load rc:', rc, flush=True)

# Find .data section
print('Finding .data section...', flush=True)
with open(dll_path, 'rb') as f:
    pe_data = f.read()

e_lfanew = struct.unpack('<I', pe_data[0x3c:0x40])[0]
opt_hdr_size = struct.unpack('<H', pe_data[e_lfanew+20:e_lfanew+22])[0]
sh_off = e_lfanew + 24 + opt_hdr_size

for i in range(struct.unpack('<H', pe_data[e_lfanew+6:e_lfanew+8])[0]):
    sh = pe_data[sh_off+i*40:sh_off+i*40+40]
    name = sh[:8].rstrip(b'\x00').decode('utf-8', errors='replace')
    if name == '.data':
        data_rva = struct.unpack('<I', sh[12:16])[0]
        data_vsize = struct.unpack('<I', sh[8:12])[0]
        data_rawsize = struct.unpack('<I', sh[16:20])[0]
        print('Data: RVA=%x, VSize=%x, RawSize=%x' % (data_rva, data_vsize, data_rawsize), flush=True)
        break

data_ptr = handle + data_rva
print('Data ptr:', hex(data_ptr), flush=True)

# Read nvar at known offset
print('Reading nvar at 0x211644...', flush=True)
buf = (ctypes.c_int * 1)()
ctypes.memmove(buf, ctypes.c_void_p(data_ptr + 0x211644), 4)
print('nvar:', buf[0], flush=True)

print('Done', flush=True)
