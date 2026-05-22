"""Test all Windows SFI methods."""
import sys
sys.path.insert(0, 'src')

from pystata_x.sfi._engine import initialize
initialize()

from pystata_x.sfi._strategy import _STRATEGY
from pystata_x.sfi._engine import _LIB

_LIB.StataSO_Execute(b'sysuse auto, clear')
print('var_count:', _STRATEGY.var_count())
print('obs_count:', _STRATEGY.obs_count())

print('\n=== Types ===')
for i in range(1, 13):
    vn = _STRATEGY.get_var_name(i)
    vt = _STRATEGY.get_var_type(i)
    vf = _STRATEGY.get_var_format(i)
    print(f'  var{i} {vn}: type={hex(vt)} fmt="{vf}"')

print('\n=== Data ===')
print('  price[1]:', _STRATEGY.data_get(2, 1))
print('  price[2]:', _STRATEGY.data_get(2, 2))
print('  mpg[1]:', _STRATEGY.data_get(3, 1))
print('  trunk[1]:', _STRATEGY.data_get(6, 1))

print('\n=== String ===')
print('  make[1]:', repr(_STRATEGY.get_string(1, 1)))
print('  price[1] formatted:', repr(_STRATEGY.get_string(2, 1)))
print('  weight[1] formatted:', repr(_STRATEGY.get_string(7, 1)))

print('\n=== Scalar ===')
_LIB.StataSO_Execute(b'scalar __px_test = 42.5')
print('  get_scalar_value(__px_test):', _STRATEGY.get_scalar_value('__px_test'))
_STRATEGY.set_scalar_value('__px_test2', 99)
print('  set_scalar_value + get:', _STRATEGY.get_scalar_value('__px_test2'))

print('\n=== Macro ===')
_STRATEGY.set_macro_global('px_gtest', 'hello_world')
print('  get_macro_global:', repr(_STRATEGY.get_macro_global('px_gtest')))
_STRATEGY.set_macro_local('px_ltest', 'local_val')
print('  get_macro_local:', repr(_STRATEGY.get_macro_local('px_ltest')))
print('  c(level):', repr(_STRATEGY.get_macro_global('c(level)')))

print('\n=== find_var_index ===')
for name in ['price', 'mpg', 'rep78', 'weight', 'foreign', 'make']:
    idx = _STRATEGY.find_var_index(name)
    print(f'  {name}: {idx}')

print('\nAll Windows tests completed!')
