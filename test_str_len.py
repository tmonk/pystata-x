from pystata_x.sfi._engine import initialize, call_double
initialize()
import pystata_x.sfi._engine as eng

eng._LIB.StataSO_Execute(b'sysuse auto, clear')
eng._LIB.StataSO_Execute(b'global tm = "Hello42"')

for strlen in ['str10', 'str20', 'str100', 'str500', 'str2048', 'str3000']:
    eng._LIB.StataSO_Execute(b'capture drop __px_st')
    eng._LIB.StataSO_Execute(f'gen {strlen} __px_st = "$tm"'.encode())
    nvar = int(call_double('_bist_nvar'))
    status = 'OK' if nvar > 12 else 'FAIL'
    print(f'  {strlen}: {status}', flush=True)
    if nvar > 12:
        break
