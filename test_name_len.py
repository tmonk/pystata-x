from pystata_x.sfi._engine import initialize, call_double
initialize()
import pystata_x.sfi._engine as eng

eng._LIB.StataSO_Execute(b'sysuse auto, clear')

from pystata_x.sfi._core import _init_px_ref, _x86_read_encoded_str
_init_px_ref()

# Test different name lengths
for name in ['a', 'aa', 't1', 't13', 'test', 'test1', 'testg', 'testgl', 'testglo', 'testglob', 'testgloba', 'testglobal']:
    # Set the global
    eng._LIB.StataSO_Execute(f'global {name} = "VALUE123"'.encode())
    
    # Read via gen + $
    eng._LIB.StataSO_Execute(f'capture drop __px_n'.encode())
    eng._LIB.StataSO_Execute(f'gen str20 __px_n = "${name}"'.encode())
    val = _x86_read_encoded_str(lambda o1: '__px_n[1]', 0)
    print(f'  {name:10s} (${{{name}}}): {val!r}', flush=True)
