"""Debug string reading: does gen str from string var work?"""
import ctypes, json, sys
sys.path.insert(0, 'src')

dll_path = r'C:\Program Files\StataNow19\se-64.dll'
dll = ctypes.WinDLL(dll_path)
dll.StataSO_Main.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_char_p)]
dll.StataSO_Main.restype = ctypes.c_int
dll.StataSO_Main(2, (ctypes.c_char_p * 2)(b'stata', b'-q'))
dll.StataSO_Execute.argtypes = [ctypes.c_char_p]
dll.StataSO_Execute.restype = ctypes.c_int

dll.StataSO_Execute(b'sysuse auto, clear')

with open('src/pystata_x/sfi/manifests/manifest-windows-x86_64.json') as f:
    m = json.load(f)
scratch_rva = m['memory_offsets']['scratch_buffer_rva']

def exe(cmd):
    if isinstance(cmd, str): cmd = cmd.encode()
    return dll.StataSO_Execute(cmd)

def scratch():
    buf = (ctypes.c_double * 1)()
    ctypes.memmove(buf, ctypes.c_void_p(dll._handle + scratch_rva), 8)
    return buf[0]

# Test: can we read make[1] by encoding it?
print("=== Test: gen from make[1] ===")
rc = exe('capture drop __px_t')
rc = exe('gen str2045 __px_t = make[1]')
print('gen rc:', rc)

# Test encoding of first char
alphabet = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_%.-+#/'
pos = 1
rc = exe(f'scalar __px_c = strpos("{alphabet}", substr(__px_t[1], {pos}, 1))')
rc = exe('capture drop __px_t2')
rc = exe('gen double __px_t2 = __px_c')
code = scratch()
print(f'char {pos}: strpos={code}')
if code and int(code) > 0:
    idx = int(code) - 2
    if 0 <= idx < len(alphabet):
        print(f'  decoded: "{alphabet[idx]}"')

# Encode first 6 chars as single scalar
terms = []
for i in range(6):
    p = i + 1
    pw = 256 ** i
    terms.append(f'cond(substr(__px_t[1], {p}, 1) == "", 0, (strpos("{alphabet}", substr(__px_t[1], {p}, 1)) + 1) * {pw})')
expr = ' + '.join(terms)
print(f'\nExpression length: {len(expr)}')
rc = exe(f'scalar __px_c0 = {expr}')
if rc != 0:
    print('scalar chunk 0 FAILED, rc=', rc)
else:
    rc = exe('capture drop __px_t2')
    rc = exe('gen double __px_t2 = __px_c0')
    val = scratch()
    print(f'chunk 0 encoded value: {val}')
    if val and val > 0:
        raw_int = int(val)
        decoded = ''
        for i in range(6):
            b = (raw_int >> (i * 8)) & 0xFF
            if b == 0:
                break
            idx = b - 2
            if 0 <= idx < len(alphabet):
                decoded += alphabet[idx]
            else:
                break
        print(f'  decoded: "{decoded}"')

# Second chunk
terms = []
for i in range(6):
    p = 7 + i
    pw = 256 ** i
    terms.append(f'cond(substr(__px_t[1], {p}, 1) == "", 0, (strpos("{alphabet}", substr(__px_t[1], {p}, 1)) + 1) * {pw})')
expr = ' + '.join(terms)
print(f'\nExpression length: {len(expr)}')
rc = exe(f'scalar __px_c1 = {expr}')
if rc != 0:
    print('scalar chunk 1 FAILED, rc=', rc)
else:
    # Need to gen to see the value
    rc = exe('capture drop __px_t2')
    rc = exe('gen double __px_t2 = __px_c1')
    val = scratch()
    print(f'chunk 1 encoded value: {val}')

print('\n=== Test: gen from AMC Concord literal ===')
rc = exe('capture drop __px_t')
rc = exe('gen str2045 __px_t = "AMC Concord"')
terms = []
for i in range(6):
    p = i + 1
    pw = 256 ** i
    terms.append(f'cond(substr(__px_t[1], {p}, 1) == "", 0, (strpos("{alphabet}", substr(__px_t[1], {p}, 1)) + 1) * {pw})')
expr = ' + '.join(terms)
rc = exe(f'scalar __px_c0 = {expr}')
rc = exe('capture drop __px_t2')
rc = exe('gen double __px_t2 = __px_c0')
val = scratch()
decoded = ''
raw_int = int(val)
for i in range(6):
    b = (raw_int >> (i * 8)) & 0xFF
    if b == 0: break
    idx = b - 2
    if 0 <= idx < len(alphabet): decoded += alphabet[idx]
print(f'Direct literal: "{decoded}"')

print('\nDone')
