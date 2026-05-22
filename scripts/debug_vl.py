"""Debug vl_get_label for non-existent values."""
import sys
sys.path.insert(0, 'src')

from pystata_x.sfi._engine import initialize
initialize()

from pystata_x.sfi._strategy import _STRATEGY
from pystata_x.sfi._engine import _LIB

_LIB.StataSO_Execute(b'sysuse auto, clear')
_LIB.StataSO_Execute(b'label define yesno 0 No 1 Yes')
_LIB.StataSO_Execute(b'label values foreign yesno')

# Test vl_get_label for various values
for v in [-1, 0, 1, 2, 3, 999]:
    lbl = _STRATEGY.vl_get_label('yesno', float(v))
    print(f'  vl_get_label(yesno, {v}): {repr(lbl)}')

# Test :label directly
_LIB.StataSO_Execute(b'capture local __px_t1 : label yesno 0')
_LIB.StataSO_Execute(b'capture drop __px_tmp')
cmd = b'capture gen str2000 __px_tmp = "`__px_t1'" + b"'" + b'"'
_LIB.StataSO_Execute(cmd)
print(f'  :label yesno 0 via local: reading...')

# Read with encoding
alphabet = ' abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_%.-+#/'
from pystata_x.sfi._engine import _MEMORY_OFFSETS
import ctypes
scratch_rva = _MEMORY_OFFSETS.get('scratch_buffer_rva', 0x3b3cc00)
addr = _LIB._handle + scratch_rva

for chunk in range(2):
    terms = []
    for i in range(5):
        p = chunk*5 + i + 1
        pw = 256 ** i
        terms.append(f'cond(substr(__px_tmp[1], {p}, 1) == "", 0, (strpos("{alphabet}", substr(__px_tmp[1], {p}, 1)) + 1) * {pw})')
    expr = ' + '.join(terms)
    _LIB.StataSO_Execute(f'scalar __px_ec{chunk} = {expr}'.encode())
    _LIB.StataSO_Execute(b'capture drop __px_ed')
    _LIB.StataSO_Execute(f'gen double __px_ed = __px_ec{chunk}'.encode())
    buf = (ctypes.c_double * 1)()
    ctypes.memmove(buf, ctypes.c_void_p(addr), 8)
    raw = buf[0]
    decoded = ''
    raw_int = int(raw)
    for i in range(5):
        b = (raw_int >> (i*8)) & 0xFF
        if b == 0: break
        idx = b - 2
        if 0 <= idx < len(alphabet): decoded += alphabet[idx]
        else: break
    print(f'  chunk {chunk}: raw={raw}, decoded="{decoded}"')
    if b == 0: break

# Test 999 which doesn't exist
_LIB.StataSO_Execute(b'capture local __px_t2 : label yesno 999')
_LIB.StataSO_Execute(b'capture drop __px_tmp')
cmd2 = b'capture gen str2000 __px_tmp = "`__px_t2'" + b"'" + b'"'
_LIB.StataSO_Execute(cmd2)
for chunk in range(2):
    terms = []
    for i in range(5):
        p = chunk*5 + i + 1
        pw = 256 ** i
        terms.append(f'cond(substr(__px_tmp[1], {p}, 1) == "", 0, (strpos("{alphabet}", substr(__px_tmp[1], {p}, 1)) + 1) * {pw})')
    expr = ' + '.join(terms)
    _LIB.StataSO_Execute(f'scalar __px_ec{chunk} = {expr}'.encode())
    _LIB.StataSO_Execute(b'capture drop __px_ed')
    _LIB.StataSO_Execute(f'gen double __px_ed = __px_ec{chunk}'.encode())
    buf = (ctypes.c_double * 1)()
    ctypes.memmove(buf, ctypes.c_void_p(addr), 8)
    raw = buf[0]
    decoded = ''
    raw_int = int(raw)
    for i in range(5):
        b = (raw_int >> (i*8)) & 0xFF
        if b == 0: break
        idx = b - 2
        if 0 <= idx < len(alphabet): decoded += alphabet[idx]
        else: break
    print(f'  chunk {chunk}: raw={raw}, decoded="{decoded}"')
    if b == 0: break

print('\nDone')
