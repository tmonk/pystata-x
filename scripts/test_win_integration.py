"""Integration test for pystata-x on Windows using scratch buffer."""

# Test 1: scratch buffer basics
print("=== Test 1: Scratch buffer read ===")
import ctypes, struct, json, sys

with open('src/pystata_x/sfi/manifests/manifest-windows-x86_64.json') as f:
    m = json.load(f)
mo = m.get('memory_offsets', {})
print('scratch_rva:', hex(mo.get('scratch_buffer_rva', 0)))

dll_path = r'C:\Program Files\StataNow19\se-64.dll'
dll = ctypes.WinDLL(dll_path)

dll.StataSO_Main.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_char_p)]
dll.StataSO_Main.restype = ctypes.c_int
dll.StataSO_Main(2, (ctypes.c_char_p * 2)(b'stata', b'-q'))
dll.StataSO_Execute.argtypes = [ctypes.c_char_p]
dll.StataSO_Execute.restype = ctypes.c_int

dll.StataSO_Execute(b'sysuse auto, clear')

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
scratch_off = mo.get('scratch_buffer_offset', 0)

def read_scratch():
    buf = (ctypes.c_double * 1)()
    ctypes.memmove(buf, ctypes.c_void_p(data_ptr + scratch_off), 8)
    return buf[0]

# Test: gen with scalar intermediate
dll.StataSO_Execute(b'scalar __px_v = price[1]')
dll.StataSO_Execute(b'capture drop __px_t')
dll.StataSO_Execute(b'gen double __px_t = __px_v')
print('price[1]:', int(read_scratch()), '(expected 4099)')

dll.StataSO_Execute(b'scalar __px_v = price[74]')
dll.StataSO_Execute(b'capture drop __px_t')
dll.StataSO_Execute(b'gen double __px_t = __px_v')
print('price[74]:', int(read_scratch()), '(expected 13466)')

dll.StataSO_Execute(b'scalar __px_v = _N')
dll.StataSO_Execute(b'capture drop __px_t')
dll.StataSO_Execute(b'gen double __px_t = __px_v')
print('_N:', int(read_scratch()), '(expected 74)')

dll.StataSO_Execute(b'scalar __px_v = mpg[1]')
dll.StataSO_Execute(b'capture drop __px_t')
dll.StataSO_Execute(b'gen double __px_t = __px_v')
print('mpg[1]:', int(read_scratch()), '(expected 22)')

# Test 2: var names via local macro
print("\n=== Test 2: Variable names ===")
dll.StataSO_Execute(b'local __px_n : variable 1')
# Get first char by encoding via scalar
dll.StataSO_Execute(b"scalar __px_c = strpos('abcdefghijklmnopqrstuvwxyz','p')")
dll.StataSO_Execute(b'capture drop __px_t')
dll.StataSO_Execute(b'gen double __px_t = __px_c')
# strpos('abc...','p') = 16
print('strpos for p:', int(read_scratch()), '(expected 16)')

# Test 3: Engine init + strategy
print("\n=== Test 3: Engine init ===")
sys.path.insert(0, 'src')
from pystata_x.sfi._engine import initialize
initialize()

from pystata_x.sfi._strategy import _STRATEGY
print('Strategy:', type(_STRATEGY).__name__)
print('var_count:', _STRATEGY.var_count())

# var_count should be 0 (no dataset in initialized engine)
# Test with auto loaded manually
dll.StataSO_Execute(b'sysuse auto, clear')
print('var_count (after sysuse):', _STRATEGY.var_count())
print('obs_count:', _STRATEGY.obs_count())

print("\nDone")
