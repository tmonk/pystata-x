from pystata_x.sfi._engine import initialize, call_double
initialize()
import pystata_x.sfi._engine as eng

eng._LIB.StataSO_Execute(b'sysuse auto, clear')
eng._LIB.StataSO_Execute(b'scalar mystr = "HelloStrScalar"')
eng._LIB.StataSO_Execute(b'capture drop __px_ss')
eng._LIB.StataSO_Execute(b'gen str2000 __px_ss = scalar(mystr)')

eng._LIB.StataSO_Execute(b'capture drop __px_t')
eng._LIB.StataSO_Execute(b'gen double __px_t = .')
nv_t = int(call_double('_bist_nvar'))

# Test: substr on __px_ss[1]
eng._LIB.StataSO_Execute(b'replace __px_t = strlen(__px_ss[1])')
val = call_double('_bist_data', 1, nv_t)
print('strlen(__px_ss[1]) = ' + repr(val), flush=True)

# Test: cond expression
eng._LIB.StataSO_Execute(b'replace __px_t = cond(substr(__px_ss[1], 1, 1) == "", 0, 42)')
val2 = call_double('_bist_data', 1, nv_t)
print('cond test = ' + repr(val2), flush=True)

# Test: strpos with __px_ref
from pystata_x.sfi._core import _init_px_ref
_init_px_ref()

eng._LIB.StataSO_Execute(b'replace __px_t = strpos(__px_ref[1], substr(__px_ss[1], 1, 1))')
val3 = call_double('_bist_data', 1, nv_t)
print('strpos test = ' + repr(val3), flush=True)
