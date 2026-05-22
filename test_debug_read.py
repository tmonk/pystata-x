from pystata_x.sfi._engine import initialize, call_double
initialize()
import pystata_x.sfi._engine as eng

eng._LIB.StataSO_Execute(b'sysuse auto, clear')

from pystata_x.sfi._core import _init_px_ref, _x86_read_encoded_str
_init_px_ref()
print(f'nvar after init: {int(call_double("_bist_nvar"))}', flush=True)

# Create source var
eng._LIB.StataSO_Execute(b'global tm = "Hello42"')
eng._LIB.StataSO_Execute(b'capture drop __px_mv')
eng._LIB.StataSO_Execute(b'gen str2048 __px_mv = "$tm"')
nvar = int(call_double('_bist_nvar'))
print(f'nvar after mv: {nvar}', flush=True)

# Now call the encoding helper
val = _x86_read_encoded_str(lambda o1: '__px_mv[1]', 0)
print(f'Read result: {val!r}', flush=True)

# Check nvar after read
nvar2 = int(call_double('_bist_nvar'))
print(f'nvar after read: {nvar2}', flush=True)
