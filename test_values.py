from pystata_x.sfi._engine import initialize, call_double
initialize()
import pystata_x.sfi._engine as eng

eng._LIB.StataSO_Execute(b'sysuse auto, clear')

from pystata_x.sfi._core import _init_px_ref, _x86_read_encoded_str
_init_px_ref()

for value in ['VALUE123', 'HelloWorld42', 'Hello', 'World42', 'testglobal']:
    eng._LIB.StataSO_Execute(f'global testval = "{value}"'.encode())
    eng._LIB.StataSO_Execute(b'capture drop __px_v')
    eng._LIB.StataSO_Execute(b'gen str20 __px_v = "$testval"')
    val = _x86_read_encoded_str(lambda o1: '__px_v[1]', 0)
    print(f'  {value:20s} -> {val!r}', flush=True)
