from pystata_x.sfi._engine import initialize, call_double
initialize()
import pystata_x.sfi._engine as eng

eng._LIB.StataSO_Execute(b'sysuse auto, clear')
eng._LIB.StataSO_Execute(b'scalar mystr = "HelloStrScalar"')

from pystata_x.sfi._core import _init_px_ref, _x86_read_encoded_str
_init_px_ref()

# Method 1: gen with `name' expansion
eng._LIB.StataSO_Execute(b'capture drop __px_ss')
eng._LIB.StataSO_Execute(b'gen str2000 __px_ss = "`mystr\'"')
val = _x86_read_encoded_str(lambda o1: '__px_ss[1]', 0)
print(f'Method 1 (`mystr\'): {val!r}')

# Method 2: local assignment via display
eng._LIB.StataSO_Execute(b'local __tmp : display scalar(mystr)')
eng._LIB.StataSO_Execute(b'capture drop __px_ss2')
eng._LIB.StataSO_Execute(b'gen str2000 __px_ss2 = "`__tmp\'"')
val2 = _x86_read_encoded_str(lambda o1: '__px_ss2[1]', 0)
print(f'Method 2 (display scalar): {val2!r}')

# Method 3: use scalar() in gen (might work for string too?)
eng._LIB.StataSO_Execute(b'capture drop __px_ss3')
eng._LIB.StataSO_Execute(b'capture gen str2000 __px_ss3 = scalar(mystr)')
nv = int(call_double('_bist_nvar'))
if nv > 12:
    val3 = _x86_read_encoded_str(lambda o1: '__px_ss3[1]', 0)
    print(f'Method 3 (scalar()): {val3!r}')
else:
    print('Method 3 (scalar()): FAILED - var not created')
