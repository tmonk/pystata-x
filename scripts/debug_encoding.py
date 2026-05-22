"""Debug extended macro functions on Windows Stata."""
import ctypes, sys, json
sys.path.insert(0, 'src')

dll_path = r'C:\Program Files\StataNow19\se-64.dll'
dll = ctypes.WinDLL(dll_path)
dll.StataSO_Main.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_char_p)]
dll.StataSO_Main.restype = ctypes.c_int
dll.StataSO_Main(2, (ctypes.c_char_p * 2)(b'stata', b'-q'))
dll.StataSO_Execute.argtypes = [ctypes.c_char_p]
dll.StataSO_Execute.restype = ctypes.c_int

dll.StataSO_Execute(b'sysuse auto, clear')

def exe(cmd):
    if isinstance(cmd, str): cmd = cmd.encode()
    return dll.StataSO_Execute(cmd)

# Test various local macro patterns
print('=== Testing local macro patterns ===')
tests = [
    ('local a = 5', 'simple local'),
    ('local b : variable 1', 'extended :variable'),
    ('local c : type price', 'extended :type'),
    ('local d : var label price', 'extended :var label'),
    ('local e : display 2+2', 'extended :display'),
    ('local f _N', 'local with ='),
    ('local g = _N', 'local with = _N'),
]

for cmd, desc in tests:
    rc = exe(cmd)
    print(f'  [{rc}] {desc}: {cmd}')

# Test: does :variable need to reference a var name not index?
rc = exe('local h : variable price')  # Use name, not index
print(f'  [{rc}] :variable price: local h : variable price')

# Test: does describe work?
rc = exe('describe')
print(f'  [{rc}] describe')

# Test: what about _N?
rc = exe('local i = _N')
print(f'  [{rc}] local _N: rc={rc}')

# Now try to read _N via other methods
rc = exe('scalar __px_nobs = _N')
print(f'  [{rc}] scalar _N')

# Test: levelsof
rc = exe('levelsof price in 1/1')
print(f'  [{rc}] levelsof price in 1/1')

# Test: describe, returning variable name info
rc = exe('quietly describe, short')
print(f'  [{rc}] describe, short')

print('\nDone')
