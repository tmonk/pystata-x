"""Debug var label and value label macros."""
import sys
sys.path.insert(0, 'src')

from pystata_x.sfi._engine import initialize
initialize()

from pystata_x.sfi._strategy import _STRATEGY
from pystata_x.sfi._engine import _LIB
from pystata_x.sfi._manifest import _MEMORY_OFFSETS
import ctypes

_LIB.StataSO_Execute(b'sysuse auto, clear')
_LIB.StataSO_Execute(b'label define yesno 0 No 1 Yes')
_LIB.StataSO_Execute(b'label values foreign yesno')

scratch_rva = _MEMORY_OFFSETS.get('scratch_buffer_rva', 0x3b3cc00)
addr = _LIB._handle + scratch_rva
alphabet = ' abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_%.-+#/'

def scratch():
    buf = (ctypes.c_double * 1)()
    ctypes.memmove(buf, ctypes.c_void_p(addr), 8)
    return buf[0]

def encode_read(src):  
    """Read a str value using encoding via scalar intermediates."""
    result = ''
    for chunk in range(3):
        terms = []
        for i in range(5):
            p = chunk*5 + i + 1
            pw = 256 ** i
            terms.append(f'cond(substr({src}, {p}, 1) == "", 0, (strpos("{alphabet}", substr({src}, {p}, 1)) + 1) * {pw})')
        expr = ' + '.join(terms)
        _LIB.StataSO_Execute(f'scalar __px_ec{chunk} = {expr}'.encode())
        _LIB.StataSO_Execute(b'capture drop __px_ed')
        _LIB.StataSO_Execute(f'gen double __px_ed = __px_ec{chunk}'.encode())
        raw = scratch()
        if raw is None or raw <= 0: break
        decoded = ''
        raw_int = int(raw)
        for i in range(5):
            b = (raw_int >> (i*8)) & 0xFF
            if b == 0: break
            idx = b - 2
            if 0 <= idx < len(alphabet): decoded += alphabet[idx]
        result += decoded
        if b == 0: break
    return result

# Test 1: Direct gen with `:var label make'
_LIB.StataSO_Execute(b'capture drop __px_z')
rc = _LIB.StataSO_Execute(b'gen str2000 __px_z = `:var label make\'')
print(f'Test 1 - gen __px_z from `:var label make\' rc={rc}')
result = encode_read('__px_z[1]')
print(f'  result: "{result}"')

# Test 2: Try with local macro first
_LIB.StataSO_Execute(b'local __tmp : var label make')
_LIB.StataSO_Execute(b'capture drop __px_z')
_LIB.StataSO_Execute(b'gen str2000 __px_z = "`__tmp\'"')
print(f'\nTest 2 - gen __px_z from local rc={rc}')
result = encode_read('__px_z[1]')
print(f'  result: "{result}"')

# Test 3: `:value label foreign'
_LIB.StataSO_Execute(b'capture drop __px_z')
rc = _LIB.StataSO_Execute(b'gen str2000 __px_z = `:value label foreign\'')
print(f'\nTest 3 - gen __px_z from `:value label foreign\' rc={rc}')
result = encode_read('__px_z[1]')
print(f'  result: "{result}"')

# Test 4: `:label yesno 0'
_LIB.StataSO_Execute(b'capture drop __px_z')
rc = _LIB.StataSO_Execute(b'gen str2000 __px_z = `:label yesno 0\'')
print(f'\nTest 4 - gen __px_z from `:label yesno 0\' rc={rc}')
result = encode_read('__px_z[1]')
print(f'  result: "{result}"')

# Test 5: `:label yesno 1'
_LIB.StataSO_Execute(b'capture drop __px_z')
rc = _LIB.StataSO_Execute(b'gen str2000 __px_z = `:label yesno 1\'')
print(f'\nTest 5 - gen __px_z from `:label yesno 1\' rc={rc}')
result = encode_read('__px_z[1]')
print(f'  result: "{result}"')

print('\nDone')
