"""Corrected test: gen __px_get AFTER loading dataset, then data_get works."""
import ctypes
import struct

dll_path = r'C:\Program Files\StataNow19\se-64.dll'
dll = ctypes.WinDLL(dll_path)
handle = dll._handle

dll.StataSO_Main.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_char_p)]
dll.StataSO_Main.restype = ctypes.c_int
dll.StataSO_Main(2, (ctypes.c_char_p * 2)(b'stata', b'-q'))
dll.StataSO_Execute.argtypes = [ctypes.c_char_p]
dll.StataSO_Execute.restype = ctypes.c_int

with open(dll_path, 'rb') as f:
    pe_data = f.read()
e_lfanew = struct.unpack('<I', pe_data[0x3c:0x40])[0]
opt_hdr_size = struct.unpack('<H', pe_data[e_lfanew+20:e_lfanew+22])[0]
sh_off = e_lfanew + 24 + opt_hdr_size
for i in range(struct.unpack('<H', pe_data[e_lfanew+6:e_lfanew+8])[0]):
    sh = pe_data[sh_off + i*40:sh_off + i*40 + 40]
    name = sh[:8].rstrip(b'\x00').decode('utf-8', errors='replace')
    if name == '.data':
        data_rva = struct.unpack('<I', sh[12:16])[0]
        break
data_ptr = handle + data_rva

SCRATCH_OFF = 0x922C00

def scratch_val():
    buf = (ctypes.c_double * 1)()
    ctypes.memmove(buf, ctypes.c_void_p(data_ptr + SCRATCH_OFF), 8)
    return buf[0]

# Load auto, then create temp variable
print('=== Test: load auto, create temp, read values ===')
dll.StataSO_Execute(b'sysuse auto, clear')
dll.StataSO_Execute(b'capture drop __px_t')
dll.StataSO_Execute(b'gen double __px_t = 0')
print('After gen __px_t: scratch=%.0f (should be 0)' % scratch_val())

# Now replace with price[1]
rc = dll.StataSO_Execute(b'replace __px_t = price[1] in 1')
print('replace price[1] rc=%d: scratch=%.0f (should be 4099)' % (rc, scratch_val()))

# Different obs
rc = dll.StataSO_Execute(b'replace __px_t = price[2] in 1')
print('replace price[2]: scratch=%.0f (should be 4749)' % scratch_val())

rc = dll.StataSO_Execute(b'replace __px_t = price[74] in 1')
print('replace price[74]: scratch=%.0f (should be 13466)' % scratch_val())

# Different vars
rc = dll.StataSO_Execute(b'replace __px_t = mpg[1] in 1')
print('replace mpg[1]: scratch=%.0f (should be 22)' % scratch_val())

rc = dll.StataSO_Execute(b'replace __px_t = weight[1] in 1')
print('replace weight[1]: scratch=%.0f (should be 2930)' % scratch_val())

rc = dll.StataSO_Execute(b'replace __px_t = rep78[1] in 1')
print('replace rep78[1]: scratch=%.0f (should be 3)' % scratch_val())

rc = dll.StataSO_Execute(b'replace __px_t = foreign[1] in 1')
print('replace foreign[1]: scratch=%.0f (should be 0)' % scratch_val())

# Now test: read via gen (single command)
print('\n=== Test: gen double = varname[obs] ===')
dll.StataSO_Execute(b'drop __px_t')
rc = dll.StataSO_Execute(b'gen double __px_t = price[1]')
print('gen price[1]: scratch=%.0f (should be 4099)' % scratch_val())

dll.StataSO_Execute(b'drop __px_t')
rc = dll.StataSO_Execute(b'gen double __px_t = mpg[10]')
print('gen mpg[10]: scratch=%.0f (should be 14)' % scratch_val())

dll.StataSO_Execute(b'drop __px_t')
rc = dll.StataSO_Execute(b'gen double __px_t = length[10]')
print('gen length[10]: scratch=%.0f (should be 179)' % scratch_val())

# Try with expressions
dll.StataSO_Execute(b'drop __px_t')
rc = dll.StataSO_Execute(b'gen double __px_t = price[1] + mpg[1]')
print('gen price[1]+mpg[1]: scratch=%.0f (should be 4121)' % scratch_val())

# Try string var read
print('\n=== Test: read string (make) via encode ===')
dll.StataSO_Execute(b'drop __px_t')
dll.StataSO_Execute(b'capture drop __px_enc')
dll.StataSO_Execute(b'gen double __px_enc = .')

# For strings, we need to encode characters as doubles
# make[1] should be "AMC Concord"
# Encode first 6 chars "AMC Co"
chunk1_terms = []
src = 'make[1]'
for i in range(6):
    pos = i + 1
    pow256 = 256 ** i
    chunk1_terms.append('(strpos("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_", substr(' + src + ', ' + str(pos) + ', 1)) + 1) * ' + str(pow256))
expr = ' + '.join(chunk1_terms)
rc = dll.StataSO_Execute(b'replace __px_enc = ' + expr.encode() + b' in 1')
rv = scratch_val()
print('Encoded chunk1:', rv)
tmp = int(rv)
decoded = ''
for i in range(6):
    b = (tmp >> (i * 8)) & 0xFF
    if b == 0:
        break
    decoded += chr(b)
print('Decoded chunk1: "' + decoded + '"')

# Encode chars 7-12
chunk2_terms = []
for i in range(6):
    pos = 7 + i
    pow256 = 256 ** i
    chunk2_terms.append('(strpos("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_", substr(' + src + ', ' + str(pos) + ', 1)) + 1) * ' + str(pow256))
expr = ' + '.join(chunk2_terms)
rc = dll.StataSO_Execute(b'replace __px_enc = ' + expr.encode() + b' in 1')
rv2 = scratch_val()
tmp2 = int(rv2)
decoded2 = ''
for i in range(6):
    b = (tmp2 >> (i * 8)) & 0xFF
    if b == 0:
        break
    decoded2 += chr(b)
print('Decoded: "' + decoded + decoded2 + '"')

print('\nDone')
