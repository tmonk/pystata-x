"""Test pystata_x engine initialization on Windows."""
import sys
import os

sys.path.insert(0, r'C:\Users\tom\projects\pystata-x\src')

# Set STATA_LIB_PATH to make sure engine finds the right DLL
os.environ['STATA_LIB_PATH'] = r'C:\Program Files\StataNow19\se-64.dll'

print('Importing engine...', flush=True)
from pystata_x.sfi._engine import initialize

print('Initializing...', flush=True)
try:
    initialize()
    print('Engine initialized!', flush=True)
    
    print('StataSO_Execute test...', flush=True)
    from pystata_x.sfi._engine import _LIB
    _LIB.StataSO_Execute.restype = ctypes.c_int
    _LIB.StataSO_Execute.argtypes = [ctypes.c_char_p]
    rc = _LIB.StataSO_Execute(b'sysuse auto, clear')
    print('sysuse auto rc:', rc, flush=True)
    
except Exception as e:
    import traceback
    print('Error:', e, flush=True)
    traceback.print_exc()
