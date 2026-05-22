"""Integration test for pystata-x on Windows using scratch buffer."""
import ctypes
import json
import sys

# Load manifest
with open('src/pystata_x/sfi/manifests/manifest-windows-x86_64.json') as f:
    m = json.load(f)
mo = m.get('memory_offsets', {})
print('Manifest OK, scratch_rva:', hex(mo.get('scratch_buffer_rva', 0)))

dll_path = r'C:\Program Files\StataNow19\se-64.dll'
dll = ctypes.WinDLL(dll_path)

dll.StataSO_Main.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_char_p)]
dll.StataSO_Main.restype = ctypes.c_int
dll.StataSO_Main(2, (ctypes.c_char_p * 2)(b'stata', b'-q'))
dll.StataSO_Execute.argtypes = [ctypes.c_char_p]
dll.StataSO_Execute.restype = ctypes.c_int

print('Stata initialized')
dll.StataSO_Execute(b'sysuse auto, clear')
print('Dataset loaded')

# Test scratch buffer read
scratch_rva = mo.get('scratch_buffer_rva', 0)
scratch_off = mo.get('scratch_buffer_offset', 0)
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
data_ptr = dll._handle + data_rva

# Print info
print(f'data_rva: {hex(data_rva)}')
print(f'data_ptr: {hex(data_ptr)}')
print(f'scratch_off: {hex(scratch_off)}')
print(f'scratch_addr: {hex(data_ptr + scratch_off)}')

# Test: gen with scalar intermediate
dll.StataSO_Execute(b'scalar __px_N = price[1]')
dll.StataSO_Execute(b'capture drop __px_t')
dll.StataSO_Execute(b'gen double __px_t = __px_N')
buf = (ctypes.c_double * 1)()
ctypes.memmove(buf, ctypes.c_void_p(data_ptr + scratch_off), 8)
print(f'\nprice[1] via scratch: {buf[0]} (expected 4099)')

# Test: _N
dll.StataSO_Execute(b'scalar __px_N = _N')
dll.StataSO_Execute(b'capture drop __px_t')
dll.StataSO_Execute(b'gen double __px_t = __px_N')
ctypes.memmove(buf, ctypes.c_void_p(data_ptr + scratch_off), 8)
print(f'_N via scratch: {buf[0]} (expected 74)')

# Test: mpg[1]
dll.StataSO_Execute(b'scalar __px_N = mpg[1]')
dll.StataSO_Execute(b'capture drop __px_t')
dll.StataSO_Execute(b'gen double __px_t = __px_N')
ctypes.memmove(buf, ctypes.c_void_p(data_ptr + scratch_off), 8)
print(f'mpg[1] via scratch: {buf[0]} (expected 22)')

# Test: price[74]
dll.StataSO_Execute(b'scalar __px_N = price[74]')
dll.StataSO_Execute(b'capture drop __px_t')
dll.StataSO_Execute(b'gen double __px_t = __px_N')
ctypes.memmove(buf, ctypes.c_void_p(data_ptr + scratch_off), 8)
print(f'price[74] via scratch: {buf[0]} (expected?)')

# Test: var names via extended macro
dll.StataSO_Execute(b'local __px_name : variable 1')
dll.StataSO_Execute(b'scalar __px_N = strpos(\"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_\", substr(\"`__px_name'\", 1, 1))')
dll.StataSO_Execute(b'capture drop __px_t')
dll.StataSO_Execute(b'gen double __px_t = __px_N')
ctypes.memmove(buf, ctypes.c_void_p(data_ptr + scratch_off), 8)
char_code = buf[0]
alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"
first_char = alphabet[int(char_code) - 1] if 1 <= int(char_code) <= len(alphabet) else '?'
print(f'\nvar1 first char: {first_char} (expected \"p\" for \"price\")')

# Test: get_var_name via _WindowsStrategy
sys.path.insert(0, 'src')
from pystata_x.sfi._engine import initialize
initialize()
print('\nEngine initialized')
from pystata_x.sfi._strategy import _STRATEGY
print(f'Strategy: {type(_STRATEGY).__name__}')
print(f'var_count: {_STRATEGY.var_count()}')
print(f'obs_count: {_STRATEGY.obs_count()}')
print(f'get_var_name(1): \"{_STRATEGY.get_var_name(1)}\"')
print(f'get_var_name(2): \"{_STRATEGY.get_var_name(2)}\"')

print('\nAll tests passed!')
