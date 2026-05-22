from pystata_x.sfi._engine import initialize, call_double
initialize()
import pystata_x.sfi._engine as eng

eng._LIB.StataSO_Execute(b'sysuse auto, clear')

eng._LIB.StataSO_Execute(b'global t1 = "VALUE123"')
eng._LIB.StataSO_Execute(b'local __lt "$t1"')
eng._LIB.StataSO_Execute(b'capture drop __px_lt')
eng._LIB.StataSO_Execute(b'gen str20 __px_lt = "`__lt\'"')

from pystata_x.sfi._core import _init_px_ref, _x86_read_encoded_str
_init_px_ref()
val = _x86_read_encoded_str(lambda o1: '__px_lt[1]', 0)
print(f'$t1 expansion: {val!r}')

# Now the same but WITHOUT the $ in the local command
eng._LIB.StataSO_Execute(b'local __lt2 "VALUE"')
eng._LIB.StataSO_Execute(b'capture drop __px_lt2')
eng._LIB.StataSO_Execute(b'gen str20 __px_lt2 = "`__lt2\'"')
val2 = _x86_read_encoded_str(lambda o1: '__px_lt2[1]', 0)
print(f'Direct local: {val2!r}')
