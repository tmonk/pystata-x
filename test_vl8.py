from pystata_x.sfi._engine import initialize, call_double
initialize()
import pystata_x.sfi._engine as eng

eng._LIB.StataSO_Execute(b'sysuse auto, clear')

from pystata_x.sfi._core import _init_px_ref, _x86_read_encoded_str
_init_px_ref()

# First check current labels
eng._LIB.StataSO_Execute(b'local __tmp : label list')
eng._LIB.StataSO_Execute(b'capture drop __px_z')
eng._LIB.StataSO_Execute(b'gen str2000 __px_z = "`__tmp\'"')
val = _x86_read_encoded_str(lambda o1: '__px_z[1]', 0)
print('Initial labels: ' + repr(val))

# Define a label (auto has yesno already)
eng._LIB.StataSO_Execute(b'label define test99 0 "aa" 1 "bb", add')

# Check again
eng._LIB.StataSO_Execute(b'local __tmp : label list')
eng._LIB.StataSO_Execute(b'capture drop __px_z2')
eng._LIB.StataSO_Execute(b'gen str2000 __px_z2 = "`__tmp\'"')
val2 = _x86_read_encoded_str(lambda o1: '__px_z2[1]', 0)
print('After define: ' + repr(val2))

# Try attach it
eng._LIB.StataSO_Execute(b'label values rep78 test99')
eng._LIB.StataSO_Execute(b'capture drop __px_z3')
eng._LIB.StataSO_Execute(b'gen str2000 __px_z3 = "`__tmp\'"')
val3 = _x86_read_encoded_str(lambda o1: '__px_z3[1]', 0)
print('After attach: ' + repr(val3))
