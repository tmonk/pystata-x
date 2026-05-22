from pystata_x.sfi._engine import initialize, call_double
initialize()
import pystata_x.sfi._engine as eng

eng._LIB.StataSO_Execute(b'sysuse auto, clear')
eng._LIB.StataSO_Execute(b'global tm = "Hello42"')

# Get nvar before
nv0 = int(call_double('_bist_nvar'))
print(f'nvar before: {nv0}', flush=True)

for strlen in ['str10', 'str20', 'str100', 'str500', 'str2048', 'str3000']:
    eng._LIB.StataSO_Execute(b'capture drop __px_t')
    eng._LIB.StataSO_Execute(f'gen {strlen} __px_t = "$tm"'.encode())
    nvar_now = int(call_double('_bist_nvar'))
    status = 'OK' if nvar_now > nv0 else 'FAIL'
    print(f'  {strlen}: {status} (nvar={nvar_now})', flush=True)
    nv0 = nvar_now
