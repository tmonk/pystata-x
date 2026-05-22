"""Quick search for _bist_ functions in Stata directory DLLs."""
import ctypes
import os

stata_dir = r'C:\Program Files\StataNow19'
kernel32 = ctypes.windll.kernel32

print(f'Searching in {stata_dir}', flush=True)

# Check just the main DLL and any .pyd files
for fname in os.listdir(stata_dir):
    fname_lower = fname.lower()
    if not (fname_lower.endswith('.dll') or fname_lower.endswith('.pyd')):
        continue
    fpath = os.path.join(stata_dir, fname)
    try:
        dll = ctypes.WinDLL(fpath)
        # Check several _bist_ function names
        for bname in [b'_bist_nobs', b'_bist_nvar', b'_bist_data', b'_bist_varname']:
            try:
                addr = kernel32.GetProcAddress(ctypes.c_void_p(dll._handle), bname)
                if addr:
                    print(f'{fpath}: {bname.decode()} @ {addr:#x}', flush=True)
            except:
                pass
        kernel32.FreeLibrary(dll._handle)
    except Exception as e:
        print(f'{fpath}: load error: {e}', flush=True)

print('Done', flush=True)
