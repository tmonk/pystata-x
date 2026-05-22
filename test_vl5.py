from pystata_x.sfi._engine import initialize, call_double
initialize()
import pystata_x.sfi._engine as eng

eng._LIB.StataSO_Execute(b'sysuse auto, clear')
eng._LIB.StataSO_Execute(b'label define test1 0 "a" 1 "b"')
eng._LIB.StataSO_Execute(b'label define yesno 0 "No" 1 "Yes"')
eng._LIB.StataSO_Execute(b'label values foreign yesno')

from pystata_x.sfi._core import _init_px_ref, _x86_read_encoded_str
_init_px_ref()

# Test label list via local
eng._LIB.StataSO_Execute(b'local __tmp : label list')
eng._LIB.StataSO_Execute(b'capture drop __px_l')
eng._LIB.StataSO_Execute(b'gen str2000 __px_l = "`__tmp\'"')
val = _x86_read_encoded_str(lambda o1: '__px_l[1]', 0)
print('label list: ' + repr(val))

# Test directly: what's in __tmp?
eng._LIB.StataSO_Execute(b'capture drop __px_t')
eng._LIB.StataSO_Execute(b'gen str2000 __px_t = "hello"')
eng._LIB.StataSO_Execute(b'replace __px_t = "`__tmp\'" in 1')
val2 = _x86_read_encoded_str(lambda o1: '__px_t[1]', 0)
print('__tmp value: ' + repr(val2))
