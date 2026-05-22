"""Find Stata internal symbols via pattern matching or import lib."""
import ctypes
import os
import struct

stata_dir = r'C:\Program Files\StataNow19'

# 1. Check for PDB files
print('Searching for debug symbols...')
for fname in os.listdir(stata_dir):
    if fname.endswith('.pdb'):
        print(f'  PDB: {fname}')
    if fname.endswith('.map'):
        print(f'  MAP: {fname}')
    if fname.endswith('.lib'):
        print(f'  LIB: {fname}')

# 2. Check utilities directory
util_dir = os.path.join(stata_dir, 'utilities')
if os.path.isdir(util_dir):
    print(f'\nUtilities dir contents:')
    for fname in sorted(os.listdir(util_dir)):
        if not fname.startswith('.'):
            print(f'  {fname}')

# 3. Check Python directory
py_dir = r'C:\Program Files\StataNow19\utilities\Python311'
if os.path.isdir(py_dir):
    print(f'\nPython dir contents:')
    for fname in sorted(os.listdir(py_dir)):
        print(f'  {fname}')

# 4. Try to find _bist_nobs in the DLL via scanning the .text section
print(f'\nScanning se-64.dll .text section for _bist_nobs-like patterns...')
dll_path = os.path.join(stata_dir, 'se-64.dll')

with open(dll_path, 'rb') as f:
    data = f.read()

# Parse PE headers to find .text section offset
e_lfanew = struct.unpack('<I', data[0x3c:0x40])[0]
file_header = data[e_lfanew+4:e_lfanew+24]
number_of_sections = struct.unpack('<H', file_header[2:4])[0]
magic = struct.unpack('<H', data[e_lfanew+24:e_lfanew+26])[0]

if magic == 0x20b:  # PE32+
    optional_header_size = struct.unpack('<H', file_header[16:18])[0]
    section_headers_offset = e_lfanew + 24 + optional_header_size
else:
    section_headers_offset = e_lfanew + 24 + 224  # PE32

print(f'Number of sections: {number_of_sections}')
print(f'Section headers at offset: {section_headers_offset:#x}')

for i in range(number_of_sections):
    sh_offset = section_headers_offset + i * 40
    sname = data[sh_offset:sh_offset+8].rstrip(b'\x00').decode(errors='replace')
    virtual_size = struct.unpack('<I', data[sh_offset+8:sh_offset+12])[0]
    virtual_address = struct.unpack('<I', data[sh_offset+12:sh_offset+16])[0]
    raw_size = struct.unpack('<I', data[sh_offset+16:sh_offset+20])[0]
    raw_offset = struct.unpack('<I', data[sh_offset+20:sh_offset+24])[0]
    print(f'  {sname}: VA={virtual_address:#010x}, Raw=[{raw_offset:#010x}-{raw_offset+raw_size:#010x}], Size={raw_size}')

# Find .text section
text_rva = None
text_offset = None
text_size = None
for i in range(number_of_sections):
    sh_offset = section_headers_offset + i * 40
    sname = data[sh_offset:sh_offset+8].rstrip(b'\x00').decode(errors='replace')
    virtual_size = struct.unpack('<I', data[sh_offset+8:sh_offset+12])[0]
    virtual_address = struct.unpack('<I', data[sh_offset+12:sh_offset+16])[0]
    raw_size = struct.unpack('<I', data[sh_offset+16:sh_offset+20])[0]
    raw_offset = struct.unpack('<I', data[sh_offset+20:sh_offset+24])[0]
    if sname == '.text':
        text_rva = virtual_address
        text_offset = raw_offset
        text_size = raw_size
        print(f'\n.text section: RVA={text_rva:#x}, file_offset={text_offset:#x}, size={text_size}')

# Search for signed function addresses that match _bist_nobs known RVA
# We know that StataSO_Main is at ordinal 154, RVA=0x01de48b0
# The export table tells us se-64.dll has 161 exports
print(f'\nChecking known _bist_ RVA references from Linux manifest...')
# On Linux, _bist_nobs has a specific VM address relative to base
# On Windows, the RVA could be anywhere. Let's search for _bist_ patterns
# by looking for known function signatures.

# _bist_nobs on x86_64 Linux: a thin wrapper around 0x825a5e (bytecode interpreter)
# Pattern: mov rcx, <constant>; call <bytecode_interpreter>
# But this is Linux-specific.

# Actually, let's just see if there's an sfi/lib path we missed
print('\nChecking for SFI library or DLL...')
for root, dirs, files in os.walk(stata_dir):
    for fname in files:
        if 'sfi' in fname.lower():
            print(f'  {os.path.join(root, fname)}')
        if 'bist' in fname.lower():
            print(f'  {os.path.join(root, fname)}')
        if fname == 'sfi.pyd':
            print(f'  FOUND: {os.path.join(root, fname)}')
