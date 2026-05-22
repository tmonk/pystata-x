"""Final verification of macro and c() value reads."""
import sys
sys.path.insert(0, 'src')

from pystata_x.sfi._engine import initialize
initialize()

from pystata_x.sfi._strategy import _STRATEGY
from pystata_x.sfi._engine import _LIB

_LIB.StataSO_Execute(b'sysuse auto, clear')

_STRATEGY.set_macro_global('px_test_g', 'hello_global')
print('get_macro_global:', repr(_STRATEGY.get_macro_global('px_test_g')))

print('c(level):', repr(_STRATEGY.get_macro_global('c(level)')))
print('c(pi):', repr(_STRATEGY.get_macro_global('c(pi)')))
