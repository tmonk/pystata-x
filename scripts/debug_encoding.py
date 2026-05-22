"""Debug get_macro_global vs direct gen approach."""
import sys
sys.path.insert(0, 'src')

from pystata_x.sfi._engine import initialize
initialize()

from pystata_x.sfi._strategy import _STRATEGY
from pystata_x.sfi._engine import _LIB
from pystata_x.sfi._manifest import _MEMORY_OFFSETS
import ctypes

_LIB.StataSO_Execute(b'sysuse auto, clear')

# Simulate what _gen_from_str does for get_macro_global
name = 'px_test_g'
_LIB.StataSO_Execute(f'global {name} = "hello_global"'.encode())

# Direct test 1: what does the exact command produce?
cmd = b'gen str2000 __px_test = "$px_test_g"'
_LIB.StataSO_Execute(b'capture drop __px_test')
rc = _LIB.StataSO_Execute(cmd)
print(f'Direct gen rc={rc}')

# Read the encoded value
alphabet = ' abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_%.-+#/'
# First 5 chars
terms = []
for i in range(5):
    p = i + 1
    pw = 256 ** i
    terms.append(f'cond(substr(__px_test[1], {p}, 1) == "", 0, (strpos("{alphabet}", substr(__px_test[1], {p}, 1)) + 1) * {pw})')
expr = ' + '.join(terms)
_LIB.StataSO_Execute(f'scalar __px_c0 = {expr}'.encode())
_LIB.StataSO_Execute(b'capture drop __px_d')
_LIB.StataSO_Execute(b'gen double __px_d = __px_c0')
addr = _LIB._handle + _MEMORY_OFFSETS.get('scratch_buffer_rva', 0x3b3cc00)
buf = (ctypes.c_double * 1)()
ctypes.memmove(buf, ctypes.c_void_p(addr), 8)
val = buf[0]
print(f'  chunk 0 encoded: {val}')
decoded = ''
raw_int = int(val)
for i in range(5):
    b = (raw_int >> (i * 8)) & 0xFF
    if b == 0: break
    idx = b - 2
    if 0 <= idx < len(alphabet): decoded += alphabet[idx]
print(f'  decoded: "{decoded}"')

# Now test via the actual method
print(f'\nDirect get_macro_global: "{_STRATEGY.get_macro_global("px_test_g")}"')

# Test c(level) directly
cmd2 = b'gen str2000 __px_test = c(level)'
_LIB.StataSO_Execute(b'capture drop __px_test')
rc2 = _LIB.StataSO_Execute(cmd2)
print(f'\nc(level) gen rc={rc2}')

terms = []
for i in range(3):
    p = i + 1
    pw = 256 ** i
    terms.append(f'cond(substr(__px_test[1], {p}, 1) == "", 0, (strpos("{alphabet}", substr(__px_test[1], {p}, 1)) + 1) * {pw})')
expr = ' + '.join(terms)
_LIB.StataSO_Execute(f'scalar __px_c0 = {expr}'.encode())
_LIB.StataSO_Execute(b'capture drop __px_d')
_LIB.StataSO_Execute(b'gen double __px_d = __px_c0')
ctypes.memmove(buf, ctypes.c_void_p(addr), 8)
val = buf[0]
decoded = ''
raw_int = int(val)
for i in range(3):
    b = (raw_int >> (i * 8)) & 0xFF
    if b == 0: break
    idx = b - 2
    if 0 <= idx < len(alphabet): decoded += alphabet[idx]
print(f'  decoded: "{decoded}"')

print(f'Direct get_macro_global("c(level)"): "{_STRATEGY.get_macro_global("c(level)")}"')
print('\nDone')
