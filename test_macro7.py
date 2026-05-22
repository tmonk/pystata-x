from pystata_x.sfi._engine import initialize, call_double
initialize()
import pystata_x.sfi._engine as eng

eng._LIB.StataSO_Execute(b'sysuse auto, clear')
eng._LIB.StataSO_Execute(b'global atest = HolaMundo42')

from pystata_x.sfi._core import _init_px_ref, _x86_read_encoded_str
_init_px_ref()

# Does local __tmp atest work directly?
eng._LIB.StataSO_Execute(b'local __tmp HolaMundo42')
eng._LIB.StataSO_Execute(b'capture drop __px_a')
eng._LIB.StataSO_Execute(b'gen str20 __px_a = "`__tmp\'"')
val = _x86_read_encoded_str(lambda o1: '__px_a[1]', 0)
print(f'Direct local: {val!r}')

# Test: $atest expansion
eng._LIB.StataSO_Execute(b'local __tmp2 "$atest"')
eng._LIB.StataSO_Execute(b'capture drop __px_b')
eng._LIB.StataSO_Execute(b'gen str20 __px_b = "`__tmp2\'"')
val2 = _x86_read_encoded_str(lambda o1: '__px_b[1]', 0)
print(f'Expansion via local: {val2!r}')

# Test: local with = first
eng._LIB.StataSO_Execute(b'local __tmp3 = "$atest"')
eng._LIB.StataSO_Execute(b'capture drop __px_c')
eng._LIB.StataSO_Execute(b'gen str20 __px_c = "`__tmp3\'"')
val3 = _x86_read_encoded_str(lambda o1: '__px_c[1]', 0)
print(f'Expansion via = local: {val3!r}')

# Test: use 'ext' macro function
eng._LIB.StataSO_Execute(b'local __tmp4 : extended macro display "$atest"')
eng._LIB.StataSO_Execute(b'capture drop __px_d')
eng._LIB.StataSO_Execute(b'gen str20 __px_d = "`__tmp4\'"')
val4 = _x86_read_encoded_str(lambda o1: '__px_d[1]', 0)
print(f'Extended macro display: {val4!r}')
