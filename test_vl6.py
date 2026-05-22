from pystata_x.sfi._engine import initialize, call_double
initialize()
import pystata_x.sfi._engine as eng

eng._LIB.StataSO_Execute(b'sysuse auto, clear')
eng._LIB.StataSO_Execute(b'label define test1 0 "a" 1 "b"')
eng._LIB.StataSO_Execute(b'label define yesno 0 "No" 1 "Yes"')
eng._LIB.StataSO_Execute(b'label values foreign yesno')

from pystata_x.sfi._core import _init_px_ref, _x86_read_encoded_str
_init_px_ref()

# Test various label-related commands
for method, test_cmd, expect in [
    ('label yesno 0', b'local __tmp : label yesno 0', 'No'),
    ('label yesno 1', b'local __tmp : label yesno 1', 'Yes'),
    ('value label foreign', b'local __tmp : value label foreign', 'yesno'),
    ('label list', b'local __tmp : label list', 'yesno test1'),
    ('label dir', b'local __tmp : label dir', 'yesno test1'),
]:
    eng._LIB.StataSO_Execute(test_cmd)
    eng._LIB.StataSO_Execute(b'capture drop __px_z')
    eng._LIB.StataSO_Execute(b'gen str2000 __px_z = "`__tmp\'"')
    val = _x86_read_encoded_str(lambda o1: '__px_z[1]', 0)
    print(method + ': ' + repr(val))
