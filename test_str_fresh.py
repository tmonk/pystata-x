from pystata_x.sfi._engine import initialize, call_double
initialize()
import pystata_x.sfi._engine as eng

eng._LIB.StataSO_Execute(b'sysuse auto, clear')
eng._LIB.StataSO_Execute(b'global tm = "Hello42"')

nv0 = int(call_double('_bist_nvar'))

for i, slen in enumerate([10, 11, 18, 20, 200]):
    varname = f'__px_t{i}'
    eng._LIB.StataSO_Execute(f'gen str{slen} {varname} = "$tm"'.encode())
    nv = int(call_double('_bist_nvar'))
    status = 'OK' if nv > nv0 else 'FAIL'
    print(f'  str{slen} ({varname}): {status}', flush=True)
    nv0 = nv
