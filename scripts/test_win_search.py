"""Search for _bist_ symbols across Stata's directory structure."""
import ctypes
import os
import struct

stata_dir = r'C:\Program Files\StataNow19'
kernel32 = ctypes.windll.kernel32

# Search all .dll, .pyd, .exe in Stato directory recursively
print('Scanning for _bist_ symbols in all executables...')
for root, dirs, files in os.walk(stata_dir):
    for fname in files:
        if not fname.lower().endswith(('.dll', '.pyd', '.exe')):
            continue
        fpath = os.path.join(root, fname)
        try:
            dll = ctypes.WinDLL(fpath)
            # Quick check for the presence of a _bist_ function
            addr = kernel32.GetProcAddress(ctypes.c_void_p(dll._handle), b'_bist_nobs')
            if addr and addr != -1:
                print(f'  FOUND _bist_nobs in {fpath} @ {addr:#x}')
                continue
            # Try mangled name
            addr = kernel32.GetProcAddress(ctypes.c_void_p(dll._handle), b'_bist_nvar')
            if addr and addr != -1:
                print(f'  FOUND _bist_nvar in {fpath}')
        except:
            pass
        finally:
            try:
                ctypes.windll.kernel32.FreeLibrary(dll._handle)
            except:
                pass

print('\nScan complete.')

# Also check environment PATH for other DLLs
print('\nChecking Python DLL search path...')
path_dirs = os.environ.get('PATH', '').split(';')
for pdir in path_dirs:
    if not os.path.isdir(pdir):
        continue
    for fname in os.listdir(pdir):
        if not fname.lower().endswith('.dll'):
            continue
        fpath = os.path.join(pdir, fname)
        try:
            dll = ctypes.WinDLL(fpath)
            addr = kernel32.GetProcAddress(ctypes.c_void_p(dll._handle), b'_bist_nobs')
            if addr and addr != -1:
                print(f'  FOUND _bist_nobs in PATH: {fpath}')
        except:
            pass
        finally:
            try:
                ctypes.windll.kernel32.FreeLibrary(dll._handle)
            except:
                pass
