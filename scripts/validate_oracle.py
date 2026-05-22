"""Validate the Windows oracle."""
import json, sys

with open('tests/e2e/oracle_windows.json') as f:
    o = json.load(f)

print(f'Oracle has {len(o)} top-level keys:')
for k, v in sorted(o.items()):
    if isinstance(v, list):
        print(f'  {k}: [{len(v)} items]')
        for i, item in enumerate(v[:3]):
            print(f'    [{i}]: {repr(item)[:60]}')
        if len(v) > 3:
            print(f'    ... ({len(v)-3} more)')
    elif isinstance(v, dict):
        print(f'  {k}: {len(v)} entries')
        for kk, vv in list(v.items())[:3]:
            print(f'    {kk}: {repr(vv)[:60]}')
    else:
        print(f'  {k}: {repr(v)[:60]}')

# Validate key expectations
assert o['var_count'] == 12, f'Expected 12 vars, got {o["var_count"]}'
assert o['obs_count'] == 74, f'Expected 74 obs, got {o["obs_count"]}'
assert len(o['var_names']) == 12
assert o['var_names'][0] == 'make'
assert o['var_names'][11] == 'foreign'
assert o['var_types'][0] == 245  # 0xf5 for string
assert o['valuelabel']['vl_get_values_yesno2'] == [0, 1]
assert o['matrix']['row_total_mymat'] == 2
assert o['matrix']['col_total_mymat'] == 2

print('\nAll assertions passed! Oracle is valid.')
