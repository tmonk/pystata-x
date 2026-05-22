"""Test Stata DLL loading on Windows."""
import ctypes
import os

# The DLL is se-64.dll on Windows, not libstata-se.so
dll_path = r'C:\Program Files\StataNow19\se-64.dll'
print(f'Loading: {dll_path}')
print(f'File exists: {os.path.exists(dll_path)}')

try:
    dll = ctypes.WinDLL(dll_path)
    print(f'DLL loaded! Handle: {dll._handle:x}')
except Exception as e:
    print(f'Failed to load DLL: {e}')
    raise

# Check StataSO exports
exports = []
stata_so_funcs = []
try:
    # Try getting by ordinal or name
    for name in ['StataSO_Main', 'StataSO_Execute', 'StataSO_Initialize']:
        try:
            func = getattr(dll, name)
            print(f'{name}: address=0x{ctypes.cast(func, ctypes.c_void_p).value:x}')
            stata_so_funcs.append(name)
        except AttributeError:
            print(f'{name}: NOT FOUND')
except Exception as e:
    print(f'Error: {e}')

print(f'Found StataSO functions: {stata_so_funcs}')

# Try to run the engine initialize path
print('\nTrying engine initialization sequence...')
system_dir = os.path.dirname(dll_path)
print(f'System dir: {system_dir}')

# Check se-64.dll size
print(f'DLL size: {os.path.getsize(dll_path):,} bytes')
