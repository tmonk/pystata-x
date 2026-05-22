from pystata_x.sfi._engine import initialize, call_double
initialize()
import pystata_x.sfi._engine as eng

eng._LIB.StataSO_Execute(b'sysuse auto, clear')

# The ONLY thing that worked before was:
# global tg2 = "SomeValue"
# local __tmp4 = "$tg2"

# Why? Because "$tg2" expands to "\"SomeValue\"" which is a valid
# expression? Or maybe $ expands correctly but we need a specific syntax?

# Let me test systematically
from pystata_x.sfi._core import _init_px_ref, _x86_read_encoded_str
_init_px_ref()

# Test 1: global with quoted value, = assignment
eng._LIB.StataSO_Execute(b'clear')
eng._LIB.StataSO_Execute(b'sysuse auto, clear')
eng._LIB.StataSO_Execute(b'global ztest = "HelloWorld42"')
eng._LIB.StataSO_Execute(b'local __tmp "$ztest"')
eng._LIB.StataSO_Execute(b'capture drop __px_z')
eng._LIB.StataSO_Execute(b'gen str20 __px_z = "`__tmp\'"')
val = _x86_read_encoded_str(lambda o1: '__px_z[1]', 0)
print(f'ztest (quoted val, local w/o =): {val!r}')

# Test 2: global with unquoted value, = assignment
eng._LIB.StataSO_Execute(b'global atest = HolaMundo42')
eng._LIB.StataSO_Execute(b'local __tmp2 "$atest"')
eng._LIB.StataSO_Execute(b'capture drop __px_z2')
eng._LIB.StataSO_Execute(b'gen str20 __px_z2 = "`__tmp2\'"')
val2 = _x86_read_encoded_str(lambda o1: '__px_z2[1]', 0)
print(f'atest (unquoted val, local w/o =): {val2!r}')

# Test 3: local with = assignment
eng._LIB.StataSO_Execute(b'local __tmp3 = "$ztest"')
eng._LIB.StataSO_Execute(b'capture drop __px_z3')
eng._LIB.StataSO_Execute(b'gen str20 __px_z3 = "`__tmp3\'"')
val3 = _x86_read_encoded_str(lambda o1: '__px_z3[1]', 0)
print(f'ztest with = assignment: {val3!r}')

# Test 4: VERY short name
eng._LIB.StataSO_Execute(b'global a = "ShortVal"')
eng._LIB.StataSO_Execute(b'local __tmp4 "$a"')
eng._LIB.StataSO_Execute(b'capture drop __px_z4')
eng._LIB.StataSO_Execute(b'gen str20 __px_z4 = "`__tmp4\'"')
val4 = _x86_read_encoded_str(lambda o1: '__px_z4[1]', 0)
print(f'short name a: {val4!r}')
