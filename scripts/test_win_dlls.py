"""Deep search for _bist_ and related symbols on Windows."""
import ctypes
import os

dll_path = r'C:\Program Files\StataNow19\se-64.dll'

# Search all DLLs in the Stata directory
stata_dir = os.path.dirname(dll_path)
print(f'All DLLs in {stata_dir}:')
for f in os.listdir(stata_dir):
    if f.lower().endswith('.dll'):
        fpath = os.path.join(stata_dir, f)
        size = os.path.getsize(fpath)
        print(f'  {f} ({size:,} bytes)')

# Try to load each DLL and check for _bist_ and StataSO exports
print('\nSearching for _bist_ in all DLLs...')
kernel32 = ctypes.windll.kernel32

for fname in sorted(os.listdir(stata_dir)):
    if not fname.lower().endswith('.dll'):
        continue
    fpath = os.path.join(stata_dir, fname)
    try:
        dll = ctypes.WinDLL(fpath)
        # Check StataSO_Main
        try:
            addr = kernel32.GetProcAddress(ctypes.c_void_p(dll._handle), b'StataSO_Main')
            if addr:
                print(f'  {fname}: StataSO_Main @ {addr:#x}')
        except:
            pass
        # Check _bist_nobs as representative
        for bist_name in [b'_bist_nobs', b'_bist_nvar', b'_bist_data', b'_bist_varname', b'bist_nobs']:
            try:
                addr = kernel32.GetProcAddress(ctypes.c_void_p(dll._handle), bist_name)
                if addr:
                    print(f'  {fname}: {bist_name.decode()} @ {addr:#x}')
            except:
                pass
    except Exception as e:
        print(f'  {fname}: load error -> {e}')
