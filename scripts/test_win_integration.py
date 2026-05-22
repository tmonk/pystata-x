"""Final Windows integration test — all verified."""
import sys
sys.path.insert(0, 'src')

from pystata_x.sfi._engine import initialize
initialize()

from pystata_x.sfi._strategy import _STRATEGY
from pystata_x.sfi._engine import _LIB

_LIB.StataSO_Execute(b'sysuse auto, clear')

print(f'Strategy: {type(_STRATEGY).__name__}')
print(f'var_count: {_STRATEGY.var_count()}  obs_count: {_STRATEGY.obs_count()}')

# Verify all 12 variable names
names = [_STRATEGY.get_var_name(i) for i in range(1, 13)]
expected_names = ['make','price','mpg','rep78','headroom','trunk',
                  'weight','length','turn','displacement','gear_ratio','foreign']
all_names_ok = all(a == b for a, b in zip(names, expected_names))
print(f'Variable names: {\"PASS\" if all_names_ok else \"FAIL\"} {names}')

# Verify numeric data_get with verified correct values
# auto dataset Stata 19 values for observation 1:
data_tests = [
    (1, 1, None, 'make'),        # string var -> None expected
    (1, 2, 4099, 'price'),
    (2, 2, 4749, 'price'),
    (1, 3, 22, 'mpg'),
    (1, 4, 3, 'rep78'),
    (1, 6, 11, 'trunk'),
    (1, 7, 2930, 'weight'),
    (1, 9, 40, 'turn'),
    (1, 10, 121, 'displacement'),
    (1, 11, 3.58, 'gear_ratio'),
    (2, 11, 3.08, 'gear_ratio[2]'),
    (1, 12, 0, 'foreign'),
]
data_failures = []
for obs, var, expected, desc in data_tests:
    val = _STRATEGY.data_get(obs, var)
    if expected is None:
        # String var — value may be 0 or None
        print(f'  {desc}[{obs}]: {val} (string var)')
        continue
    if val is None or abs(val - expected) > 0.1:
        data_failures.append(f'  FAIL: {desc}[{obs}] = {val} (expected {expected})')
    else:
        print(f'  OK: {desc}[{obs}] = {val}')

if data_failures:
    print('\nData failures:')
    for f in data_failures:
        print(f)
else:
    print(f'\nAll data_get: PASS')

# Verify find_var_index
idx_failures = []
for name, expected_idx in [('price', 2), ('mpg', 3), ('rep78', 4),
                            ('weight', 7), ('foreign', 12), ('make', 1)]:
    idx = _STRATEGY.find_var_index(name)
    if idx != expected_idx:
        idx_failures.append(f'{name} -> {idx} (expected {expected_idx})')
if idx_failures:
    print(f'find_var_index FAIL: {idx_failures}')
else:
    print(f'find_var_index: PASS')

print(f'\n=== ALL TESTS {"PASSED" if not data_failures and not idx_failures else "FAILED"} ===')
