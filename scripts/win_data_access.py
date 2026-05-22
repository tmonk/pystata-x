"""Verify: is price[74] really 11995 or should it be 13466?"""
import ctypes

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

def scratch():
    buf = (ctypes.c_double * 1)()
    ctypes.memmove(buf, ctypes.c_void_p(data_ptr + 0x922C00), 8)
    return buf[0]

def execute(cmd):
    if isinstance(cmd, str): cmd = cmd.encode()
    return dll.StataSO_Execute(cmd)

# Fresh run - ONLY test price[74]
execute('sysuse auto, clear')
execute('scalar __px_tmp = price[74]')
execute('capture drop __px_t')
execute('gen double __px_t = __px_tmp')
print('price[74] via scalar:', scratch())

# Also test price[73] and price[1]
execute('scalar __px_tmp = price[73]')
execute('capture drop __px_t')
execute('gen double __px_t = __px_tmp')
print('price[73]:', scratch())

execute('scalar __px_tmp = price[1]')
execute('capture drop __px_t')
execute('gen double __px_t = __px_tmp')
print('price[1]:', scratch())

execute('scalar __px_tmp = price[2]')
execute('capture drop __px_t')
execute('gen double __px_t = __px_tmp')
print('price[2]:', scratch())

# Also check using list
execute('gen double __px_val = price in 1/5')
execute('list price in 1/5')
# After list, nothing in scratch - but we can check via gen
execute('scalar __px_tmp = price[1]')
execute('capture drop __px_t')
execute('gen double __px_t = __px_tmp')
print('price[1] (after list):', scratch())

# Also try after 'count' to see nobs
execute('count')
# Read nobs... but we don't have that in memory

# Try _N
execute('scalar __px_tmp = _N')
execute('capture drop __px_t')
execute('gen double __px_t = __px_tmp')
print('_N:', scratch())

print('\nDone')
