from pystata_x.sfi._engine import initialize, call_double
initialize()
import pystata_x.sfi._engine as eng

eng._LIB.StataSO_Execute(b'sysuse auto, clear')

from pystata_x.sfi._core import _init_px_ref, _x86_read_encoded_str
_init_px_ref()

# Define test labels step by step
eng._LIB.StataSO_Execute(b'label define test1 0 "a" 1 "b"')
eng._LIB.StataSO_Execute(b'label define test2 0 "c" 1 "d"')

# Check label list
eng._LIB.StataSO_Execute(b'local __tmp : label list')
eng._LIB.StataSO_Execute(b'capture drop __px_v')
eng._LIB.StataSO_Execute(b'gen str2000 __px_v = "`__tmp\'"')
val = _x86_read_encoded_str(lambda o1: '__px_v[1]', 0)
print('After define: ' + repr(val))

# Try with noisylabel
eng._LIB.StataSO_Execute(b'capture noisily label define test3 0 "x"')
print('noisylabel define done', flush=True)

eng._LIB.StataSO_Execute(b'local __tmp : label list')
eng._LIB.StataSO_Execute(b'capture drop __px_v2')
eng._LIB.StataSO_Execute(b'gen str2000 __px_v2 = "`__tmp\'"')
val2 = _x86_read_encoded_str(lambda o1: '__px_v2[1]', 0)
print('After test3: ' + repr(val2))
