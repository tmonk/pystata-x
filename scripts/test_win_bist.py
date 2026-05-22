"""Test full engine initialization on Windows."""
import ctypes
import os

dll_path = r'C:\Program Files\StataNow19\se-64.dll'
dll = ctypes.WinDLL(dll_path)

_Execute = dll.StataSO_Execute
_Execute.argtypes = [ctypes.c_char_p]
_Execute.restype = ctypes.c_int

_Main = dll.StataSO_Main
_Main.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_char_p)]
_Main.restype = ctypes.c_int

# Initialize Stata first
argv = (ctypes.c_char_p * 2)(b'stata', b'-q')
print('Initializing Stata...')
rc_init = _Main(2, argv)
print(f'StataSO_Main rc: {rc_init}')

# Try some simple commands
cmds = [
    b'sysuse auto, clear',
    b'describe',
    b'display "Hello from Windows Stata"',
]
for cmd in cmds:
    rc = _Execute(cmd)
    print(f'Execute({cmd!r}) -> rc={rc}')

# Check _bist_ exports
print('\nChecking _bist_ exports...')
for name in [b'_bist_nobs', b'_bist_nvar', b'_bist_data', b'_bist_varname', b'_bist_vartype']:
    try:
        func = dll[name]
        print(f'{name.decode()}: found')
    except AttributeError:
        print(f'{name.decode()}: NOT FOUND')

# Try _bist_nobs call
print('\nTrying _bist_nobs call...')
try:
    _bist_nobs = dll[b'_bist_nobs']
    _bist_nobs.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    _bist_nobs.restype = ctypes.c_double
    result = _bist_nobs(None, None)
    print(f'_bist_nobs(NULL, NULL) = {result}')
except Exception as e:
    print(f'_bist_nobs failed: {e}')

print('\nDone')
