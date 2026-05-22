from pystata_x.sfi._engine import initialize, call_double
initialize()
import pystata_x.sfi._engine as eng

eng._LIB.StataSO_Execute(b'sysuse auto, clear')

from pystata_x.sfi._core import _init_px_ref, _x86_read_encoded_str
_init_px_ref()

# Test various extended macro functions
tests = [
    (b'local __tmp : display %9.2f = 42.5', '42.50'),
    (b'local __tmp : display "hello"', 'hello'),
    (b'local __tmp = 40 + 2', '42'),
]
for cmd, expected in tests:
    eng._LIB.StataSO_Execute(cmd)
    eng._LIB.StataSO_Execute(b'capture drop __px_z')
    eng._LIB.StataSO_Execute(b'gen str2000 __px_z = "`__tmp\'"')
    val = _x86_read_encoded_str(lambda o1: '__px_z[1]', 0)
    print(repr(cmd) + ' -> ' + repr(val) + ' (expected ' + repr(expected) + ')')

# Try with = assignment (expression)
eng._LIB.StataSO_Execute(b'local __tmp = 3 * 7')
eng._LIB.StataSO_Execute(b'capture drop __px_z2')
eng._LIB.StataSO_Execute(b'gen str2000 __px_z2 = "`__tmp\'"')
val = _x86_read_encoded_str(lambda o1: '__px_z2[1]', 0)
print('= expr: ' + repr(val) + ' (expected 21)')

# Try: capture label list output directly
eng._LIB.StataSO_Execute(b'label list')
eng._LIB.StataSO_Execute(b'capture drop __px_z3')
eng._LIB.StataSO_Execute(b'gen str2000 __px_z3 = "hello world"')
val = _x86_read_encoded_str(lambda o1: '__px_z3[1]', 0)
print('label list output: (cannot capture output buffer)')
