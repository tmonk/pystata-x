from pystata_x.sfi._engine import initialize, call_double
initialize()
import pystata_x.sfi._engine as eng

eng._LIB.StataSO_Execute(b'sysuse auto, clear')

from pystata_x.sfi._core import _init_px_ref, _x86_read_encoded_str
_init_px_ref()

nvar = int(call_double('_bist_nvar'))
print('Total vars: ' + str(nvar))

# Scan each variable for attached value labels
names_set = set()
for i in range(1, nvar + 1):
    eng._LIB.StataSO_Execute(f'local __tmp : value label {i}'.encode())
    eng._LIB.StataSO_Execute(b'capture drop __px_v')
    eng._LIB.StataSO_Execute(b'gen str2000 __px_v = "`__tmp\'"')
    val = _x86_read_encoded_str(lambda o1: '__px_v[1]', 0)
    if val:
        names_set.add(val)

print('Scanned label names: ' + repr(sorted(names_set)))
