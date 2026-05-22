from pystata_x.sfi._engine import initialize, call_double
initialize()
import pystata_x.sfi._engine as eng

eng._LIB.StataSO_Execute(b'sysuse auto, clear')
eng._LIB.StataSO_Execute(b'global tm = "Hello42"')

nv0 = int(call_double('_bist_nvar'))

for slen in [10, 11, 12, 15, 18, 20, 50, 100, 200]:
    eng._LIB.StataSO_Execute(b'capture drop __px_t')
    eng._LIB.StataSO_Execute(f'gen str{slen} __px_t = "$tm"'.encode())
    nv = int(call_double('_bist_nvar'))
    status = 'OK' if nv > nv0 else 'FAIL'
    print(f'  str{slen}: {status}', flush=True)
    nv0 = nv
