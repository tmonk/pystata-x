from pystata_x.sfi._engine import initialize, call_double
initialize()
import pystata_x.sfi._engine as eng

eng._LIB.StataSO_Execute(b'sysuse auto, clear')

from pystata_x.sfi._core import _init_px_ref, _x86_read_encoded_str
_init_px_ref()

# Set via StataSO with proper quoting
eng._LIB.StataSO_Execute(b'global testglobal = "HelloWorld42"')

# Read via gen + $ + encoding
eng._LIB.StataSO_Execute(b'capture drop __px_gg')
eng._LIB.StataSO_Execute(b'gen str2048 __px_gg = "$testglobal"')
val = _x86_read_encoded_str(lambda o1: '__px_gg[1]', 0)
print(f'Read via gen: {val!r}')

# Now use Macro.setGlobal
from pystata_x.sfi._core import Macro
Macro.setGlobal('testglobal2', 'SomeValue42')

# Read via gen + $
eng._LIB.StataSO_Execute(b'capture drop __px_gg2')
eng._LIB.StataSO_Execute(b'gen str2048 __px_gg2 = "$testglobal2"')
val2 = _x86_read_encoded_str(lambda o1: '__px_gg2[1]', 0)
print(f'Macro.setGlobal -> gen: {val2!r}')

# Read via Macro.getGlobal
val3 = Macro.getGlobal('testglobal2')
print(f'Macro.getGlobal: {val3!r}')
