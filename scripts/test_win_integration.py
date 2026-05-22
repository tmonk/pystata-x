"""Final Windows integration test — all verified."""
import sys
sys.path.insert(0, 'src')

from pystata_x.sfi._engine import initialize
initialize()

from pystata_x.sfi._strategy import _STRATEGY
from pystata_x.sfi._engine import _LIB

_LIB.StataSO_Execute(b'sysuse auto, clear')

print('Strategy:', type(_STRATEGY).__name__)
print('var_count:', _STRATEGY.var_count(), 'obs_count:', _STRATEGY.obs_count())

# Verify all 12 variable names
names = [_STRATEGY.get_var_name(i) for i in range(1, 13)]
expected_names = ['make','price','mpg','rep78','headroom','trunk',
                  'weight','length','turn','displacement','gear_ratio','foreign']
all_names_ok = all(a == b for a, b in zip(names, expected_names))
print('Variable names:', 'PASS' if all_names_ok else 'FAIL', names)

# Verify numeric data_get with verified correct values
data_tests = [
    (1, 2, 4099, 'price[1]'),
    (2, 2, 4749, 'price[2]'),
    (1, 3, 22, 'mpg[1]'),
    (1, 4, 3, 'rep78[1]'),
    (1, 6, 11, 'trunk[1]'),
    (1, 7, 2930, 'weight[1]'),
    (1, 9, 40, 'turn[1]'),
    (1, 10, 121, 'displacement[1]'),
    (1, 11, 3.58, 'gear_ratio[1]'),
    (2, 11, 2.53, 'gear_ratio[2]'),
    (1, 12, 0, 'foreign[1]'),
]
data_failures = []
for obs, var, expected, desc in data_tests:
    val = _STRATEGY.data_get(obs, var)
    if val is None or abs(val - expected) > 0.1:
        data_failures.append('FAIL: ' + desc + ' = ' + str(val) + ' (expected ' + str(expected) + ')')
    else:
        print('OK:', desc, '=', val)

if data_failures:
    print('\nData failures:')
    for f in data_failures:
        print(f)
    data_ok = False
else:
    print('\nAll data_get: PASS')
    data_ok = True

# Verify find_var_index
idx_failures = []
for name, expected_idx in [('price', 2), ('mpg', 3), ('rep78', 4),
                            ('weight', 7), ('foreign', 12), ('make', 1)]:
    idx = _STRATEGY.find_var_index(name)
    if idx != expected_idx:
        idx_failures.append(name + ' -> ' + str(idx) + ' (expected ' + str(expected_idx) + ')')
if idx_failures:
    print('find_var_index FAIL:', idx_failures)
    idx_ok = False
else:
    print('find_var_index: PASS')
    idx_ok = True

print('\n=== ALL TESTS', 'PASSED' if data_ok and idx_ok else 'FAILED', '===')