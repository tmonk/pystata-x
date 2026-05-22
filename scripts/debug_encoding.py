"""Debug var name encoding on Windows."""
import ctypes, sys
sys.path.insert(0, 'src')

dll_path = r'C:\Program Files\StataNow19\se-64.dll'
dll = ctypes.WinDLL(dll_path)
dll.StataSO_Main.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_char_p)]
dll.StataSO_Main.restype = ctypes.c_int
dll.StataSO_Main(2, (ctypes.c_char_p * 2)(b'stata', b'-q'))
dll.StataSO_Execute.argtypes = [ctypes.c_char_p]
dll.StataSO_Execute.restype = ctypes.c_int

dll.StataSO_Execute(b'sysuse auto, clear')

# Test 1: strpos with simple literal
print('=== Test strpos ===')
cmd1 = b"scalar __px_p = strpos('abcdefghijklmnopqrstuvwxyz','p')"
print('cmd1:', repr(cmd1))
dll.StataSO_Execute(cmd1)
dll.StataSO_Execute(b'capture drop __px_t')
dll.StataSO_Execute(b'gen double __px_t = __px_p')
# Read scratch
import json
with open('src/pystata_x/sfi/manifests/manifest-windows-x86_64.json') as f:
    m = json.load(f)
mo = m.get('memory_offsets', {})
scratch_rva = mo.get('scratch_buffer_rva', 0)
buf = (ctypes.c_double * 1)()
ctypes.memmove(buf, ctypes.c_void_p(dll._handle + scratch_rva), 8)
print('scalar result:', buf[0])

# Test 2: local macro + strpos
print('\n=== Test local macro ===')
dll.StataSO_Execute(b'local __px_name : variable 1')
print('After local command')

# Verify macro exists
dll.StataSO_Execute(b'gen str32 __px_test = "`__px_name\'"')
print('gen str32 with macro: rc=0 for success')

# Read its value via encoding
# First char of __px_test[1]
pos = 1
alphabet_bytes = b'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_'
# Construct command directly
cmd2 = b'scalar __px_c = strpos("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_", substr(__px_test[1], 1, 1))'
print('cmd2:', repr(cmd2))
dll.StataSO_Execute(cmd2)
dll.StataSO_Execute(b'capture drop __px_t')
dll.StataSO_Execute(b'gen double __px_t = __px_c')
ctypes.memmove(buf, ctypes.c_void_p(dll._handle + scratch_rva), 8)
print('first char code:', buf[0])

# Decode
alphabet = b'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_'
code = int(buf[0])
if 1 <= code <= len(alphabet):
    print('first char:', chr(alphabet[code - 1]), '(expected p)')

# Test 3: the exact cmd from _WindowsStrategy
print('\n=== Test _WindowsStrategy command ===')
alphabet = '"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"'
cmd3 = 'scalar __px_c = strpos(' + alphabet + ', substr("`__px_name\'"' + f', {pos}, 1))'
print('cmd3:', cmd3)
# This won't work directly because it uses macro __px_name which might not exist

# Let me test with a simpler version: replace macro with str32 variable
cmd4 = 'scalar __px_c = strpos(' + alphabet + f', substr(__px_test[1], {pos}, 1))'
print('cmd4:', cmd4)
dll.StataSO_Execute(cmd4.encode())
dll.StataSO_Execute(b'capture drop __px_t')
dll.StataSO_Execute(b'gen double __px_t = __px_c')
ctypes.memmove(buf, ctypes.c_void_p(dll._handle + scratch_rva), 8)
print('result:', buf[0])

# Test 5: Why does strpos return 22 for 'p'?
print('\n=== Debug strpos ===')
for test_char in [b'p', b'P', b'a', b'v']:
    cmd = b'scalar __px_r = strpos("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_","' + test_char + b'")'
    dll.StataSO_Execute(cmd)
    dll.StataSO_Execute(b'capture drop __px_t')
    dll.StataSO_Execute(b'gen double __px_t = __px_r')
    ctypes.memmove(buf, ctypes.c_void_p(dll._handle + scratch_rva), 8)
    print(f'  strpos("{chr(test_char[0])}"): {buf[0]}')

print('\nDone')
