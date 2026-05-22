"""Isolate macro global issue."""
import sys
sys.path.insert(0, 'src')

from pystata_x.sfi._engine import initialize
initialize()

from pystata_x.sfi._strategy import _STRATEGY
from pystata_x.sfi._engine import _LIB
from pystata_x.sfi._engine import _MEMORY_OFFSETS
import ctypes

# Test macro in clean state — no dataset loaded
print("=== No dataset ===")
_STRATEGY.set_macro_global('px_test_g', 'hello_global')
v1 = _STRATEGY.get_macro_global('px_test_g')
print(f'  No dataset get_macro_global: {repr(v1)}')

# Now load auto dataset
_LIB.StataSO_Execute(b'sysuse auto, clear')
print("\n=== With auto dataset ===")

# Run some operations that might interfere
for i in range(1, 13):
    _STRATEGY.get_var_name(i)
    _STRATEGY.get_var_type(i)
    _STRATEGY.get_var_format(i)
_STRATEGY.data_get(1, 2)
_STRATEGY.get_string(1, 1)
print("  After heavy operations...")

_STRATEGY.set_macro_global('px_test_g', 'hello_global')
v2 = _STRATEGY.get_macro_global('px_test_g')
print(f'  get_macro_global: {repr(v2)}')

# Set it again immediately
_STRATEGY.set_macro_global('px_test_g', 'hello_again')
v3 = _STRATEGY.get_macro_global('px_test_g')
print(f'  get_macro_global (hello_again): {repr(v3)}')

# Direct strogreal test for c(level)
v4 = _STRATEGY.get_macro_global('c(level)')
print(f'  c(level): {repr(v4)}')

# Local macro
_STRATEGY.set_macro_local('px_test_l', 'local_val')
v5 = _STRATEGY.get_macro_local('px_test_l')
print(f'  get_macro_local: {repr(v5)}')

print('\nDone')
