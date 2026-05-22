from pystata_x.sfi._engine import initialize, call_double
initialize()
import pystata_x.sfi._engine as eng

eng._LIB.StataSO_Execute(b'sysuse auto, clear')
eng._LIB.StataSO_Execute(b'scalar mystr = "HelloStrScalar"')

from pystata_x.sfi._core import _init_px_ref, _x86_read_encoded_str
_init_px_ref()
print('ref init done', flush=True)

# Test: does gen with scalar() work?
eng._LIB.StataSO_Execute(b'capture drop __px_ss')
eng._LIB.StataSO_Execute(b'gen str2000 __px_ss = scalar(mystr)')
nv = int(call_double('_bist_nvar'))
print('nvar after gen: ' + str(nv), flush=True)

# Read via encoding
val = _x86_read_encoded_str(lambda o1: '__px_ss[1]', 0)
print('Read result: ' + repr(val), flush=True)
