"""Test tempname on Windows."""
import sys, ctypes
sys.path.insert(0, 'src')
from pystata_x.sfi._engine import initialize, _LIB, _MEMORY_OFFSETS
initialize()

# Gen directly
_LIB.StataSO_Execute(b'gen str2000 __px_test = "\x60=tempname(1)\x27"')

# Read via scratch
addr = _LIB._handle + _MEMORY_OFFSETS['scratch_buffer_rva']
buf = (ctypes.c_double * 1)()

# Read encoded string chunks
alphabet = ' abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_%.-+#/'
for chunk in range(3):
    terms = []
    for i in range(5):
        p = chunk*5 + i + 1
        pw = 256 ** i
        terms.append(f'cond(substr(__px_test[1],{p},1)=="",0,(strpos("{alphabet}",substr(__px_test[1],{p},1))+1)*{pw})')
    expr = ' + '.join(terms)
    _LIB.StataSO_Execute(f'scalar __px_ec{chunk} = {expr}'.encode())
    _LIB.StataSO_Execute(b'capture drop __px_ed')
    _LIB.StataSO_Execute(f'gen double __px_ed = __px_ec{chunk}'.encode())
    ctypes.memmove(buf, ctypes.c_void_p(addr), 8)
    raw = buf[0]
    decoded = ''
    raw_int = int(raw)
    b_last = 0
    for i in range(5):
        b_val = (raw_int >> (i*8)) & 0xFF
        if b_val == 0: b_last = b_val; break
        idx = b_val - 2
        if 0 <= idx < len(alphabet): decoded += alphabet[idx]
    print(f'  chunk {chunk}: raw={raw} decoded="{decoded}"')
    if b_last == 0: break

# Test with _STRATEGY
from pystata_x.sfi._strategy import _STRATEGY
r = _STRATEGY.get_temp_name('')
print(f'get_temp_name: {repr(r)}')
r2 = _STRATEGY.get_temp_name('px')
print(f'get_temp_name(px): {repr(r2)}')

print('Done')
