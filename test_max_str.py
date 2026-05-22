from pystata_x.sfi._engine import initialize, call_double
initialize()
import pystata_x.sfi._engine as eng

eng._LIB.StataSO_Execute(b'sysuse auto, clear')
eng._LIB.StataSO_Execute(b'global tm = "Hello42"')

nv0 = int(call_double('_bist_nvar'))

# Binary search for the max working str length
for slen in [10, 100, 1000, 2000, 2048, 3000, 5000, 10000]:
    varname = f'__px_s{slen}'
    eng._LIB.StataSO_Execute(f'gen str{slen} {varname} = "$tm"'.encode())
    nv = int(call_double('_bist_nvar'))
    status = 'OK' if nv > nv0 else 'FAIL'
    print(f'  str{slen}: {status}', flush=True)
    if status == 'OK':
        nv0 = nv
    else:
        break
