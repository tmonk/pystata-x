"""Compare Windows and Linux manifests to detect platform alignment.

Usage: python scripts/diff_manifests.py
"""
import json, os, sys

def load_manifest(path):
    if not os.path.exists(path):
        print(f'WARNING: {path} not found')
        return {}
    with open(path) as f:
        return json.load(f)

win_path = os.path.join(os.path.dirname(__file__), '..', 'src', 'pystata_x', 'sfi', 'manifests', 'manifest-windows-x86_64.json')
linux_path = os.path.join(os.path.dirname(__file__), '..', 'src', 'pystata_x', 'sfi', 'manifests', 'manifest-linux-x86_64.json')

win = load_manifest(win_path)
linux = load_manifest(linux_path)

if not win and not linux:
    print('No manifests found.')
    sys.exit(1)
if not win:
    print(f'Windows manifest not found at {win_path}')
    sys.exit(1)
if not linux:
    print(f'Linux manifest not found at {linux_path}')
    sys.exit(1)

print('=' * 60)
print('Manifest Diff: Windows vs Linux x86_64')
print('=' * 60)

# Compare top-level keys
all_keys = set(win.keys()) | set(linux.keys())
win_only = set(win.keys()) - set(linux.keys())
linux_only = set(linux.keys()) - set(win.keys())
common = set(win.keys()) & set(linux.keys())

print(f'\nCommon keys: {len(common)}')
print(f'Windows-only: {win_only}')
print(f'Linux-only: {linux_only}')

# Compare common values
mismatches = []
match_count = 0
for key in sorted(common):
    wv = win[key]
    lv = linux[key]
    if isinstance(wv, dict) and isinstance(lv, dict):
        # Recurse
        sub_keys = set(wv.keys()) | set(lv.keys())
        for sk in sorted(sub_keys):
            swv = wv.get(sk)
            slv = lv.get(sk)
            if swv != slv:
                mismatches.append((f'{key}.{sk}', swv, slv))
            else:
                match_count += 1
    elif wv != lv:
        mismatches.append((key, wv, lv))
    else:
        match_count += 1

if mismatches:
    print(f'\nMismatches ({len(mismatches)}):')
    for key, wv, lv in mismatches:
        print(f'  {key}:')
        print(f'    Windows: {repr(wv)[:80]}')
        print(f'    Linux:   {repr(lv)[:80]}')
else:
    print(f'\nAll {match_count} common values MATCH!')

# Summary stats
print(f'\n-- Summary --')
print(f'Windows keys: {len(win)}')
print(f'Linux keys:   {len(linux)}')
print(f'Matching:     {match_count}')
print(f'Mismatches:   {len(mismatches)}')
