"""Check _bist_ symbol availability on Windows."""
import ctypes
import os
import subprocess

dll_path = r'C:\Program Files\StataNow19\se-64.dll'

# Dump all exports
result = subprocess.run(
    ['dumpbin', '/exports', dll_path],
    capture_output=True, text=True, timeout=30
)
output = result.stdout

# Search for _bist_ in exports
lines = output.split('\n')
bist_lines = [l for l in lines if '_bist_' in l]
print(f'Found {len(bist_lines)} _bist_ exports:')
for l in bist_lines:
    print(f'  {l.strip()}')

# Also check for StataSO functions
so_lines = [l for l in lines if 'StataSO' in l]
print(f'\nFound {len(so_lines)} StataSO exports:')
for l in so_lines:
    print(f'  {l.strip()}')

# Also try GetProcAddress for common bist functions
dll = ctypes.WinDLL(dll_path, use_last_error=True)
dll_handle = ctypes.c_void_p(dll._handle)
print(f'\nDLL handle: {dll_handle.value:x}')

# Try different name formats
names_to_try = [
    b'_bist_nobs',
    b'_bist_nvar',
    b'_bist_data',
    b'_bist_varname',
    b'_bist_vartype',
    b'_bist_varlabel',
    b'_bist_varformat',
    b'_bist_sdata',
    b'_bist_dir',
    b'_bist_FrameCount',
    b'_bist_framedir',
    b'_bist_global',
    b'_bist_numscalar',
    b'_bist_strscalar',
    b'_bist_value',
    b'_bist_vlmap',
    b'_bist_vlload',
    b'_bist_vlexists',
    b'_bist_macroexpand',
    b'_bist_MataFcn',
    b'_bist_MatrixGet',
    b'_bist_MatrixSet',
    b'_bist_assert',
    b'_bist_char',
    b'_bist_charval',
    b'_bist_pref',
    b'_bist_c',
    b'_bist_lb',
    b'_bist_cb',
    b'_bist_push',
    # Mangled Windows names
    b'__bist_nobs',
    b'__bist_nvar@8',
    b'_bist_nobs@8',
    b'__bist_data@16',
]

kernel32 = ctypes.windll.kernel32
for name in names_to_try:
    try:
        addr = kernel32.GetProcAddress(dll_handle, name)
        if addr:
            print(f'  FOUND: {name.decode(errors="replace")} @ 0x{addr:x}')
    except:
        pass

print('\nTry with ordinal scan...')
# If they're not exported by name, try by ordinal
# But first let's just check the total export count
print(f'Total exports: {lines[0].strip() if lines else "unknown"}')
