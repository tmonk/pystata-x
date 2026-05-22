from pystata_x.sfi._engine import initialize, call_double
initialize()
import pystata_x.sfi._engine as eng

eng._LIB.StataSO_Execute(b'sysuse auto, clear')
eng._LIB.StataSO_Execute(b'global testglobal = HelloWorld42')

from pystata_x.sfi._core import _init_px_ref, _x86_read_encoded_str
_init_px_ref()

# Method 4: compound quote macro expansion
# `"$testglobal"' — this should expand $testglobal before assignment
eng._LIB.StataSO_Execute(b'local __tmp2 = `"$testglobal"\'')
eng._LIB.StataSO_Execute(b'capture drop __px_t4')
eng._LIB.StataSO_Execute(b'gen str20 __px_t4 = "`__tmp2\'"')
val4 = _x86_read_encoded_str(lambda o1: '__px_t4[1]', 0)
print(f'Method 4: {val4!r}')

# Method 5: colon macro copy
eng._LIB.StataSO_Execute(b'local __tmp3 : copy global testglobal')
eng._LIB.StataSO_Execute(b'capture drop __px_t5')
eng._LIB.StataSO_Execute(b'gen str20 __px_t5 = "`__tmp3\'"')
val5 = _x86_read_encoded_str(lambda o1: '__px_t5[1]', 0)
print(f'Method 5: {val5!r}')

# Method 6: try with different global naming
eng._LIB.StataSO_Execute(b'global tg2 = "SomeValue"')
eng._LIB.StataSO_Execute(b'local __tmp4 = "$tg2"')
eng._LIB.StataSO_Execute(b'capture drop __px_t6')
eng._LIB.StataSO_Execute(b'gen str20 __px_t6 = "`__tmp4\'"')
val6 = _x86_read_encoded_str(lambda o1: '__px_t6[1]', 0)
print(f'Method 6: {val6!r}')

# Method 7: avoid gen entirely - use scalar to store, then read
eng._LIB.StataSO_Execute(b'scalar __px_num = `"$testglobal"\'')
# scalars are numeric... this won't work for strings
