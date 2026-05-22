from pystata_x.sfi._engine import initialize, call_double
initialize()
import pystata_x.sfi._engine as eng

eng._LIB.StataSO_Execute(b'sysuse auto, clear')
eng._LIB.StataSO_Execute(b'label define test99 0 "a" 1 "b"')

from pystata_x.sfi._core import _init_px_ref, _x86_read_encoded_str
_init_px_ref()

# : label list — should list all label names
# Try different syntaxes
for method in [
    b'local __tmp : label list',
    b'local __tmp : labels',
    b'local __tmp : lab list',
    b'local __tmp : lab li',
]:
    eng._LIB.StataSO_Execute(method)
    eng._LIB.StataSO_Execute(b'capture drop __px_z')
    eng._LIB.StataSO_Execute(b'gen str2000 __px_z = "`__tmp\'"')
    val = _x86_read_encoded_str(lambda o1: '__px_z[1]', 0)
    if val:
        print('  ' + repr(method) + ' -> ' + repr(val))
    else:
        print('  ' + repr(method) + ' -> (empty)')

# Check if test99 exists
eng._LIB.StataSO_Execute(b'local __tmp : label test99 0')
eng._LIB.StataSO_Execute(b'capture drop __px_z2')
eng._LIB.StataSO_Execute(b'gen str2000 __px_z2 = "`__tmp\'"')
val = _x86_read_encoded_str(lambda o1: '__px_z2[1]', 0)
print('label test99 0: ' + repr(val))

# Check origin label
eng._LIB.StataSO_Execute(b'local __tmp : label origin 0')
eng._LIB.StataSO_Execute(b'capture drop __px_z3')
eng._LIB.StataSO_Execute(b'gen str2000 __px_z3 = "`__tmp\'"')
val = _x86_read_encoded_str(lambda o1: '__px_z3[1]', 0)
print('label origin 0: ' + repr(val))
