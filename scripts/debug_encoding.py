"""Debug the exact pattern used by _gen_from_str."""
import ctypes, json, sys
sys.path.insert(0, 'src')

from pystata_x.sfi._engine import initialize
initialize()

from pystata_x.sfi._strategy import _STRATEGY
from pystata_x.sfi._engine import _LIB

_LIB.StataSO_Execute(b'sysuse auto, clear')

# Test 1: macro global 
print('=== Test get_macro_global ===')
_STRATEGY.set_macro_global('px_test_g', 'hello_global')

# What does the gen command actually look like?
name = 'px_test_g'
cmd = 'gen str2000 __px_gs = ' + '"$' + name + '"'
print('  Command:', cmd)

# Execute manually
import ctypes
with open('src/pystata_x/sfi/manifests/manifest-windows-x86_64.json') as f:
    m = json.load(f)
scratch_rva = m['memory_offsets']['scratch_buffer_rva']

_LIB.StataSO_Execute(b'capture drop __px_gs')
rc = _LIB.StataSO_Execute(cmd.encode())
print('  rc:', rc)

# Read via scratch encode
alphabet = ' abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_%.-+#/'
for chunk in range(3):
    terms = []
    for i in range(5):
        p = chunk * 5 + i + 1
        pw = 256 ** i
        terms.append(f'cond(substr(__px_gs[1], {p}, 1) == "", 0, (strpos("{alphabet}", substr(__px_gs[1], {p}, 1)) + 1) * {pw})')
    expr = ' + '.join(terms)
    _LIB.StataSO_Execute(f'scalar __px_en{chunk} = {expr}'.encode())
    _LIB.StataSO_Execute(b'capture drop __px_d')
    _LIB.StataSO_Execute(f'gen double __px_d = __px_en{chunk}'.encode())
    buf = (ctypes.c_double * 1)()
    ctypes.memmove(buf, ctypes.c_void_p(_LIB._handle + scratch_rva), 8)
    val = buf[0]
    decoded = ''
    raw_int = int(val)
    for i in range(5):
        b = (raw_int >> (i * 8)) & 0xFF
        if b == 0: break
        idx = b - 2
        if 0 <= idx < len(alphabet): decoded += alphabet[idx]
    print(f'  chunk {chunk}: "{decoded}"')

# Test 2: c(level)
print('\n=== Test c(level) ===')
name = 'c(level)'
cmd2 = 'gen str2000 __px_gs = ' + '`=' + name + "'"
print('  Command:', cmd2)

_LIB.StataSO_Execute(b'capture drop __px_gs')
rc2 = _LIB.StataSO_Execute(cmd2.encode())
print('  rc:', rc2)

for chunk in range(1):
    terms = []
    for i in range(3):
        p = i + 1
        pw = 256 ** i
        terms.append(f'cond(substr(__px_gs[1], {p}, 1) == "", 0, (strpos("{alphabet}", substr(__px_gs[1], {p}, 1)) + 1) * {pw})')
    expr = ' + '.join(terms)
    _LIB.StataSO_Execute(f'scalar __px_en0 = {expr}'.encode())
    _LIB.StataSO_Execute(b'capture drop __px_d')
    _LIB.StataSO_Execute(b'gen double __px_d = __px_en0')
    buf = (ctypes.c_double * 1)()
    ctypes.memmove(buf, ctypes.c_void_p(_LIB._handle + scratch_rva), 8)
    val = buf[0]
    decoded = ''
    raw_int = int(val)
    for i in range(3):
        b = (raw_int >> (i * 8)) & 0xFF
        if b == 0: break
        idx = b - 2
        if 0 <= idx < len(alphabet): decoded += alphabet[idx]
    print(f'  decoded: "{decoded}"')

print('\nDone')
