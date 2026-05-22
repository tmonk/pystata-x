"""Debug PE export table parsing."""
import struct

with open(r'C:\Program Files\StataNow19\se-64.dll', 'rb') as f:
    d = f.read()

e_lfanew = struct.unpack('<I', d[0x3c:0x40])[0]
print('e_lfanew:', hex(e_lfanew))

opt_hdr = e_lfanew + 24
magic = struct.unpack('<H', d[opt_hdr:opt_hdr+2])[0]
print('magic:', hex(magic))

# PE32+: data directories at optional_header + 112
data_dir_off = opt_hdr + 112
for i in range(16):
    rva = struct.unpack('<I', d[data_dir_off+i*8:data_dir_off+i*8+4])[0]
    sz = struct.unpack('<I', d[data_dir_off+i*8+4:data_dir_off+i*8+8])[0]
    if rva or sz:
        print(f'  dir[{i}]: rva={hex(rva)} size={sz}')

# The export table we found earlier from the full PE scan
print()
print('From earlier export scan:')
print('  Export RVA = 0x320efa0')
print('  Export size = 24328')
print('  StataSO_Main at ordinal 154, RVA = 0x01de48b0')
