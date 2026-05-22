from pystata_x.sfi._engine import initialize, call_double
initialize()
import pystata_x.sfi._engine as eng

eng._LIB.StataSO_Execute(b'sysuse auto, clear')

# Set global WITHOUT quotes (like the real _bist_global does)
eng._LIB.StataSO_Execute(b'capture noisily global testglobal = HelloWorld42')

from pystata_x.sfi._core import _init_px_ref, _x86_read_encoded_str
_init_px_ref()

# Method: copy global to local via extended macro function
eng._LIB.StataSO_Execute(b'local __tmp : copy global testglobal')
eng._LIB.StataSO_Execute(b'capture drop __px_z')
eng._LIB.StataSO_Execute(b'gen str20 __px_z = "`__tmp\'"')
val = _x86_read_encoded_str(lambda o1: '__px_z[1]', 0)
print(f': copy global testglobal: {val!r}')

# Method: macro global command
eng._LIB.StataSO_Execute(b'local __tmp2 : macro global testglobal')
eng._LIB.StataSO_Execute(b'capture drop __px_z2')
eng._LIB.StataSO_Execute(b'gen str20 __px_z2 = "`__tmp2\'"')
val2 = _x86_read_encoded_str(lambda o1: '__px_z2[1]', 0)
print(f': macro global testglobal: {val2!r}')

# Method: display %s (format as string)
eng._LIB.StataSO_Execute(b'local __tmp3 : display %s "$testglobal"')
eng._LIB.StataSO_Execute(b'capture drop __px_z3')
eng._LIB.StataSO_Execute(b'gen str20 __px_z3 = "`__tmp3\'"')
val3 = _x86_read_encoded_str(lambda o1: '__px_z3[1]', 0)
print(f': display %s testglobal: {val3!r}')
