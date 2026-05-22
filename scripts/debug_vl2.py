"""Debug vl_exists for yesno2."""
import sys
sys.path.insert(0, 'src')
from pystata_x.sfi._engine import initialize
initialize()
from pystata_x.sfi._engine import _LIB
from pystata_x.sfi._strategy import _STRATEGY

# Setup
_LIB.StataSO_Execute(b'sysuse auto, clear')
_LIB.StataSO_Execute(b'label define yesno2 0 No 1 Yes')
_LIB.StataSO_Execute(b'label values foreign yesno2')

# Debug vl_exists
print('vl_exists(yesno2):', _STRATEGY.vl_exists('yesno2'))
print('vl_get_label(yesno2, 0):', repr(_STRATEGY.vl_get_label('yesno2', 0.0)))
print('vl_get_label(yesno2, 1):', repr(_STRATEGY.vl_get_label('yesno2', 1.0)))
print('vl_get_label(yesno2, 999):', repr(_STRATEGY.vl_get_label('yesno2', 999.0)))
print('vl_get_values(yesno2):', _STRATEGY.vl_get_values('yesno2'))
print('vl_get_labels(yesno2):', _STRATEGY.vl_get_labels('yesno2'))

# Direct Stata check
_LIB.StataSO_Execute(b'capture local __px_chk : label yesno2 0')
_LIB.StataSO_Execute(b'capture drop __px_chk')
_LIB.StataSO_Execute(b'capture gen str2000 __px_chk = "\x60__px_chk\x27"')
# Read it
from pystata_x.sfi._engine import _MEMORY_OFFSETS
import ctypes
alphabet = ' abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_%.-+#/'
addr = _LIB._handle + _MEMORY_OFFSETS['scratch_buffer_rva']
for chunk in range(3):
    terms = []
    for i in range(5):
        p = chunk*5 + i + 1
        pw = 256 ** i
        terms.append(f'cond(substr(__px_chk[1],{p},1)=="",0,(strpos("{alphabet}",substr(__px_chk[1],{p},1))+1)*{pw})')
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
        b_val = (raw_int >> (i*8)) & 0xFF
        if b_val == 0: break
        idx = b_val - 2
        if 0 <= idx < len(alphabet): decoded += alphabet[idx]
    print(f'direct chunk {chunk}: raw={raw} decoded="{decoded}"')

print('\nDone')
