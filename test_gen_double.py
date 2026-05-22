from pystata_x.sfi._engine import initialize, call_double
initialize()
import pystata_x.sfi._engine as eng

eng._LIB.StataSO_Execute(b'sysuse auto, clear')
eng._LIB.StataSO_Execute(b'scalar mystr = "Hello"')

# Create __px_ref
from pystata_x.sfi._core import _init_px_ref
_init_px_ref()

# Now try to create __px_s
eng._LIB.StataSO_Execute(b'capture drop __px_s')
eng._LIB.StataSO_Execute(b'gen double __px_s = .')
nv = int(call_double('_bist_nvar'))
print(f'nvar after gen __px_s: {nv}', flush=True)

# Check var names
from pystata_x.sfi._engine import _read_var_name_x86
for i in range(nv):
    name = _read_var_name_x86(i)
    if name and 'px' in name:
        print(f'  var {i}: {name}', flush=True)
