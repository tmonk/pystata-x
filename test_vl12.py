from pystata_x.sfi._engine import initialize, call_double
initialize()
import pystata_x.sfi._engine as eng

eng._LIB.StataSO_Execute(b'sysuse auto, clear')

from pystata_x.sfi._core import _init_px_ref, _x86_read_encoded_str
from pystata_x.sfi._engine import _read_var_name_x86
_init_px_ref()

for name in ['make', 'price', 'mpg', 'forei', 'foreign', 'rep78', 'trunk', 'weight']:
    eng._LIB.StataSO_Execute(f'local __tmp : value label {name}'.encode())
    eng._LIB.StataSO_Execute(b'capture drop __px_z')
    eng._LIB.StataSO_Execute(b'gen str2000 __px_z = "`__tmp\'"')
    val = _x86_read_encoded_str(lambda o1: '__px_z[1]', 0)
    if val:
        print(f'{name}: {repr(val)}')
