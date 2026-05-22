from pystata_x.sfi._engine import initialize, call_double
initialize()
import pystata_x.sfi._engine as eng

eng._LIB.StataSO_Execute(b'sysuse auto, clear')
eng._LIB.StataSO_Execute(b'global testglobal = HelloWorld42')

from pystata_x.sfi._core import _init_px_ref, _x86_read_encoded_str
_init_px_ref()

# Method 1: local = assignment with $global
eng._LIB.StataSO_Execute(b'local __tmp = "$testglobal"')
eng._LIB.StataSO_Execute(b'capture drop __px_t')
eng._LIB.StataSO_Execute(b'gen str20 __px_t = "`__tmp\'"')
val = _x86_read_encoded_str(lambda o1: '__px_t[1]', 0)
print(f'Method 1: {val!r}')

# Method 2: direct local with known value
eng._LIB.StataSO_Execute(b'local testval = "HelloWorld42"')
eng._LIB.StataSO_Execute(b'capture drop __px_t2')
eng._LIB.StataSO_Execute(b'gen str20 __px_t2 = "`testval\'"')
val2 = _x86_read_encoded_str(lambda o1: '__px_t2[1]', 0)
print(f'Method 2: {val2!r}')

# Method 3: gen with $global directly
eng._LIB.StataSO_Execute(b'capture drop __px_t3')
eng._LIB.StataSO_Execute(b'gen str20 __px_t3 = "$testglobal"')
val3 = _x86_read_encoded_str(lambda o1: '__px_t3[1]', 0)
print(f'Method 3: {val3!r}')
