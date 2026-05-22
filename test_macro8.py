from pystata_x.sfi._engine import initialize, call_double
initialize()
import pystata_x.sfi._engine as eng

eng._LIB.StataSO_Execute(b'sysuse auto, clear')

# Set identically: global X = SomeValue (same value, different names)
eng._LIB.StataSO_Execute(b'global aaa = SomeValue')
eng._LIB.StataSO_Execute(b'global bbb = SomeValue')
eng._LIB.StataSO_Execute(b'global ccc = SomeValue')
eng._LIB.StataSO_Execute(b'global tg2 = SomeValue')

from pystata_x.sfi._core import _init_px_ref, _x86_read_encoded_str
_init_px_ref()

for name in ['aaa', 'bbb', 'ccc', 'tg2']:
    cmd = f'local __tmp "${name}"'
    eng._LIB.StataSO_Execute(cmd.encode())
    eng._LIB.StataSO_Execute(b'capture drop __px_z')
    eng._LIB.StataSO_Execute(b'gen str20 __px_z = "`__tmp\'"')
    val = _x86_read_encoded_str(lambda o1: '__px_z[1]', 0)
    print(f'${name} = {val!r}')
