from pystata_x.sfi._engine import initialize, call_double
initialize()
import pystata_x.sfi._engine as eng

eng._LIB.StataSO_Execute(b'sysuse auto, clear')

from pystata_x.sfi._core import _init_px_ref, _x86_read_encoded_str
_init_px_ref()

# Check value label for var 12 (foreign, 1-based)
eng._LIB.StataSO_Execute(b'local __tmp : value label 12')
eng._LIB.StataSO_Execute(b'capture drop __px_z')
eng._LIB.StataSO_Execute(b'gen str2000 __px_z = "`__tmp\'"')
val = _x86_read_encoded_str(lambda o1: '__px_z[1]', 0)
print('Value label var 12: ' + repr(val))

# Check value label for var 6
eng._LIB.StataSO_Execute(b'local __tmp : value label 6')
eng._LIB.StataSO_Execute(b'capture drop __px_z2')
eng._LIB.StataSO_Execute(b'gen str2000 __px_z2 = "`__tmp\'"')
val2 = _x86_read_encoded_str(lambda o1: '__px_z2[1]', 0)
print('Value label var 6: ' + repr(val2))
