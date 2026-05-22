from pystata_x.sfi._engine import initialize, call_double
initialize()
import pystata_x.sfi._engine as eng

eng._LIB.StataSO_Execute(b'sysuse auto, clear')
print('sysuse ok', flush=True)

from pystata_x.sfi._core import _init_px_ref, _x86_read_encoded_str
_init_px_ref()
print('ref init ok', flush=True)

from pystata_x.sfi._core import Macro
print('import ok', flush=True)

# Test set via Macro.setGlobal
Macro.setGlobal('testm', 'Hello42')
print('set ok', flush=True)

# Test get via gen + $
eng._LIB.StataSO_Execute(b'capture drop __px_get')
eng._LIB.StataSO_Execute(b'gen str20 __px_get = "$testm"')
print('gen ok', flush=True)

val = _x86_read_encoded_str(lambda o1: '__px_get[1]', 0)
print(f'gen + $: {val!r}', flush=True)

val2 = Macro.getGlobal('testm')
print(f'Macro.getGlobal: {val2!r}', flush=True)
