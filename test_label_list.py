from pystata_x.sfi._engine import initialize, call_double
initialize()
import pystata_x.sfi._engine as eng

eng._LIB.StataSO_Execute(b'sysuse auto, clear')

from pystata_x.sfi._core import _init_px_ref, _x86_read_encoded_str
_init_px_ref()

# Try : label list
eng._LIB.StataSO_Execute(b'local __tmp : label list')
eng._LIB.StataSO_Execute(b'capture drop __px_z')
eng._LIB.StataSO_Execute(b'gen str2000 __px_z = "`__tmp\'"')
val = _x86_read_encoded_str(lambda o1: '__px_z[1]', 0)
print('label list: ' + repr(val))

# Try `: label dir`
eng._LIB.StataSO_Execute(b'local __tmp : label dir')
eng._LIB.StataSO_Execute(b'capture drop __px_z2')
eng._LIB.StataSO_Execute(b'gen str2000 __px_z2 = "`__tmp\'"')
val2 = _x86_read_encoded_str(lambda o1: '__px_z2[1]', 0)
print('label dir: ' + repr(val2))

# Try : label list yesno (list values for a specific label)
eng._LIB.StataSO_Execute(b'local __tmp : label list yesno')
eng._LIB.StataSO_Execute(b'capture drop __px_z3')
eng._LIB.StataSO_Execute(b'gen str2000 __px_z3 = "`__tmp\'"')
val3 = _x86_read_encoded_str(lambda o1: '__px_z3[1]', 0)
print('label list yesno: ' + repr(val3))

# What does quiet label list produce?
eng._LIB.StataSO_Execute(b'capture noisily label list origin')
print('label list origin done', flush=True)
