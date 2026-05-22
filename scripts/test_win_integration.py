"""Clean integration test: test _WindowsStrategy methods."""
import ctypes
import sys
sys.path.insert(0, 'src')

print('=== Initializing pystata-x engine ===')
from pystata_x.sfi._engine import initialize
initialize()

from pystata_x.sfi._strategy import _STRATEGY
from pystata_x.sfi._engine import _LIB

print('Strategy:', type(_STRATEGY).__name__)
print()

print('=== var_count (no dataset) ===')
print('var_count:', _STRATEGY.var_count())

print('\n=== Loading auto dataset ===')
_LIB.StataSO_Execute(b'sysuse auto, clear')

print('var_count:', _STRATEGY.var_count())
print('obs_count:', _STRATEGY.obs_count())

print('\n=== Variable names ===')
for i in range(1, 13):
    vn = _STRATEGY.get_var_name(i)
    print(f'  var{i}: "{vn}"')

print('\n=== Data values ===')
tests = [(1, 1, 4099), (2, 1, 4749), (1, 2, 22), (1, 6, 2930)]
for obs, var, expected in tests:
    val = _STRATEGY.data_get(obs, var)
    match = 'OK' if abs(val - expected) < 1 else 'MISMATCH'
    print(f'  data_get(obs={obs}, var={var}): {val} (expected {expected}) [{match}]')

print('\n=== find_var_index ===')
print('  price:', _STRATEGY.find_var_index('price'))
print('  mpg:', _STRATEGY.find_var_index('mpg'))
print('  rep78:', _STRATEGY.find_var_index('rep78'))

print('\n=== get_scalar_value ===')
print('  scalar(1):', _STRATEGY.get_scalar_value('1'))

print('\n=== get_max_vars ===')
print('  maxvars:', _STRATEGY.get_max_vars())

print('\nAll tests passed!')
