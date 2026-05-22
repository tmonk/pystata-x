from pystata_x.sfi._engine import initialize, call_double
initialize()
import pystata_x.sfi._engine as eng

eng._LIB.StataSO_Execute(b'sysuse auto, clear')
eng._LIB.StataSO_Execute(b'global testglobal = HelloWorld42')

from pystata_x.sfi._core import _init_px_ref, _x86_read_encoded_str
_init_px_ref()

# Method: local WITHOUT = sign
eng._LIB.StataSO_Execute(b'local __tmp "$testglobal"')
eng._LIB.StataSO_Execute(b'capture drop __px_t')
eng._LIB.StataSO_Execute(b'gen str20 __px_t = "`__tmp\'"')
val = _x86_read_encoded_str(lambda o1: '__px_t[1]', 0)
print(f'local w/o =: {val!r} (expected "HelloWorld42")')
