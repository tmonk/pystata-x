"""Test Stata execution on Windows."""
import ctypes
import os

dll_path = r'C:\Program Files\StataNow19\se-64.dll'
dll = ctypes.WinDLL(dll_path)

# Set up function signatures
# StataSO_Execute takes a const char* and returns int
_Execute = dll.StataSO_Execute
_Execute.argtypes = [ctypes.c_char_p]
_Execute.restype = ctypes.c_int

# StataSO_Main takes argc, argv — need to set up properly
_Main = dll.StataSO_Main
_Main.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_char_p)]
_Main.restype = ctypes.c_int

print('Starting Stata initialization via StataSO_Main...')

# First, we need to initialize Stata
# On Linux, StataSO_Main(2, ["stata-se", "-q"]) initializes
# On Windows, let's try the same
import sys

# Create argv array
argv = (ctypes.c_char_p * 2)(b'stata', b'-q')
print('Calling StataSO_Main(2, argv)...')
try:
    result = _Main(2, argv)
    print(f'StataSO_Main returned: {result}')
except Exception as e:
    print(f'StataSO_Main failed: {e}')

# Try executing a command
print('\nTrying StataSO_Execute...')
try:
    result = _Execute(b'sysuse auto, clear')
    print(f'Execute rc: {result}')
    result2 = _Execute(b'describe')
    print(f'Describe rc: {result2}')
except Exception as e:
    print(f'Execute failed: {e}')

print('\nDone')
