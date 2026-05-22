"""Test pystata_x engine initialization on Windows."""
import ctypes
import sys

# Initialize Stata first
dll_path = r'C:\Program Files\StataNow19\se-64.dll'
dll = ctypes.WinDLL(dll_path)

_Main = dll.StataSO_Main
_Main.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_char_p)]
_Main.restype = ctypes.c_int

argv = (ctypes.c_char_p * 2)(b'stata', b'-q')
print('Initializing Stata...')
rc_init = _Main(2, argv)
print(f'StataSO_Main rc: {rc_init}')

# Now try to import pystata_x's engine
sys.path.insert(0, r'C:\Users\tom\projects\pystata-x\src')
sys.path.insert(0, r'C:\Users\tom\projects\pystata-x')

# Set STATA_DIR so engine can find DLL
import os
os.environ['STATA_DIR'] = r'C:\Program Files\StataNow19'

# Import engine config first
import pystata_x._config as cfg
print(f'Config STATA_DIR: {cfg.STATA_DIR}')
print(f'Config DLL_NAME: {cfg.DLL_NAME}')

# The engine expects libstata-se.so or needs config
# Let's check what DLL_NAME resolves to
print(f'Config _DLL: {cfg._DLL_PATH}')

# Try to initialize via pystata_x.sfi._engine
try:
    from pystata_x.sfi._engine import initialize
    print('Engine imported')
    initialize()
    print('Engine initialized!')
    
    # Now try some basic ops
    import pystata_x._stata_fast as _fast
    _fast._bist_configured = False
    
    from pystata_x.sfi._core import Data, Macro, Scalar, ValueLabel
    print(f'nobs: {Data.getObsTotal()}')
    print(f'nvar: {Data.getVarCount()}')
    print(f'global test: {Macro.getGlobal("c(level)")}')
except Exception as e:
    print(f'Engine init error: {e}')
    import traceback
    traceback.print_exc()
