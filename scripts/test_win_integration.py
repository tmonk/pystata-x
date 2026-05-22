"""Integration test for Windows SFI — corrected expectations."""
import ctypes
import sys
sys.path.insert(0, 'src')

from pystata_x.sfi._engine import initialize
initialize()

from pystata_x.sfi._strategy import _STRATEGY
from pystata_x.sfi._engine import _LIB

print('Strategy:', type(_STRATEGY).__name__)

_LIB.StataSO_Execute(b'sysuse auto, clear')
print('var_count:', _STRATEGY.var_count())
print('obs_count:', _STRATEGY.obs_count())

print('\n=== Variable names ===')
for i in range(1, 13):
    vn = _STRATEGY.get_var_name(i)
    print(f'  var{i}: "{vn}"')

print('\n=== Numeric data_get tests ===')
tests = [(1, 2, 4099, 'price[1]'), (2, 2, 4749, 'price[2]'),
         (74, 2, 13466, 'price[74]'),
         (1, 3, 22, 'mpg[1]'), (1, 6, 11, 'trunk[1]'),
         (1, 7, 2930, 'weight[1]'), (1, 9, 40, 'turn[1]'),
         (1, 10, 157, 'displacement[1]'),
         (1, 11, 3.58, 'gear_ratio[1]')]
all_ok = True
for obs, var, expected, desc in tests:
    val = _STRATEGY.data_get(obs, var)
    ok = abs(val - expected) < 0.01 if val is not None else False
    if not ok:
        all_ok = False
        print(f'  MISMATCH: data_get(obs={obs}, var={var}) = {val} (expected {expected}, {desc})')
    else:
        print(f'  OK: {desc} = {val}')

print(f'\nAll data_get OK: {all_ok}')

print('\n=== find_var_index ===')
names = ['price', 'mpg', 'rep78', 'weight', 'length', 'turn', 'foreign']
for name in names:
    idx = _STRATEGY.find_var_index(name)
    print(f'  {name}: {idx}')
    if idx <= 0:
        print(f'    ERROR: {name} not found')

print('\n=== String variable (make) ===')
val = _STRATEGY.data_get(1, 1)  # make is a string var
print(f'  make[1] (should be None or 0 for string var): {val}')

print('\nDone')
