from pystata_x.sfi._engine import initialize, call_double
initialize()
import pystata_x.sfi._engine as eng

eng._LIB.StataSO_Execute(b'sysuse auto, clear')

from pystata_x.sfi._core import _init_px_ref, _x86_read_encoded_str
from pystata_x.sfi._engine import _read_var_name_x86
_init_px_ref()

nvar = int(call_double('_bist_nvar'))

# Check each variable
for i in range(1, nvar + 1):
    name = _read_var_name_x86(i - 1)
    
    # Get value label
    eng._LIB.StataSO_Execute(f'local __tmp : value label {i}'.encode())
    eng._LIB.StataSO_Execute(b'capture drop __px_vl')
    eng._LIB.StataSO_Execute(b'gen str2000 __px_vl = "`__tmp\'"')
    val = _x86_read_encoded_str(lambda o1: '__px_vl[1]', 0)
    
    if val:
        print(f'Var {i} ({name}): value label = {repr(val)}')
    
# Also check : label yesno 0
eng._LIB.StataSO_Execute(b'local __tmp : label yesno 0')
eng._LIB.StataSO_Execute(b'capture drop __px_lb')
eng._LIB.StataSO_Execute(b'gen str2000 __px_lb = "`__tmp\'"')
val_lb = _x86_read_encoded_str(lambda o1: '__px_lb[1]', 0)
print(f'Label yesno 0: {repr(val_lb)}')
