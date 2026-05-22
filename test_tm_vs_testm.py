from pystata_x.sfi._engine import initialize, call_double
initialize()
import pystata_x.sfi._engine as eng

eng._LIB.StataSO_Execute(b'sysuse auto, clear')
eng._LIB.StataSO_Execute(b'global tm = "Hello42"')
eng._LIB.StataSO_Execute(b'global testm = "Hello42"')

nv0 = int(call_double('_bist_nvar'))
print(f'nv0={nv0}', flush=True)

for name, strlen in [('tm', 'str10'), ('tm', 'str20'), ('testm', 'str10'), ('testm', 'str20')]:
    eng._LIB.StataSO_Execute(b'capture drop __px_t')
    eng._LIB.StataSO_Execute(f'gen {strlen} __px_t = "${name}"'.encode())
    nv = int(call_double('_bist_nvar'))
    status = 'OK' if nv > nv0 else 'FAIL'
    print(f'  ${name} -> {strlen}: {status} (nvar={nv})', flush=True)
    nv0 = nv
