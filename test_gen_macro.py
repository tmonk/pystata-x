from pystata_x.sfi._engine import initialize, call_double
initialize()
import pystata_x.sfi._engine as eng

eng._LIB.StataSO_Execute(b'sysuse auto, clear')
eng._LIB.StataSO_Execute(b'global t1 = "VALUE123"')

from pystata_x.sfi._core import _init_px_ref, _x86_read_encoded_str
_init_px_ref()

# Test 1: gen with $expansion
eng._LIB.StataSO_Execute(b'capture drop __px_ge')
eng._LIB.StataSO_Execute(b'gen str20 __px_ge = "$t1"')
val = _x86_read_encoded_str(lambda o1: '__px_ge[1]', 0)
print(f'gen with $t1: {val!r}')

# Test 2: local with $expansion, then gen
eng._LIB.StataSO_Execute(b'local __lt "$t1"')
eng._LIB.StataSO_Execute(b'capture drop __px_ge2')
eng._LIB.StataSO_Execute(b'gen str20 __px_ge2 = "`__lt\'"')
val2 = _x86_read_encoded_str(lambda o1: '__px_ge2[1]', 0)
print(f'local + gen: {val2!r}')

# Test 3: gen with $expansion using extended gen
eng._LIB.StataSO_Execute(b'capture drop __px_ge3')
eng._LIB.StataSO_Execute(b'gen str20 __px_ge3 = `"$t1"\'')
val3 = _x86_read_encoded_str(lambda o1: '__px_ge3[1]', 0)
print(f'gen with compound quotes: {val3!r}')
