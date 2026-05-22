"""Full PE export table parsing for se-64.dll (pure Python)."""
import ctypes
import struct

dll_path = r'C:\Program Files\StataNow19\se-64.dll'

with open(dll_path, 'rb') as f:
    data = f.read()

# Parse PE header
# DOS header
e_magic = data[0:2]
if e_magic != b'MZ':
    print('Not a PE file (no MZ header)')
    exit(1)

# Get PE offset from DOS header
e_lfanew = struct.unpack('<I', data[0x3c:0x40])[0]
print(f'PE header at offset: {e_lfanew:#x}')

# PE signature
pe_sig = data[e_lfanew:e_lfanew+4]
if pe_sig != b'PE\x00\x00':
    print(f'No PE signature: {pe_sig!r}')
    exit(1)

# File header
file_header = data[e_lfanew+4:e_lfanew+24]
machine = struct.unpack('<H', file_header[0:2])[0]
number_of_sections = struct.unpack('<H', file_header[2:4])[0]
print(f'Machine: {machine:#x} ({"x86_64" if machine == 0x8664 else "x86" if machine == 0x14c else "other"})')
print(f'Sections: {number_of_sections}')

# Optional header
optional_header_offset = e_lfanew + 24
magic = struct.unpack('<H', data[optional_header_offset:optional_header_offset+2])[0]
print(f'Optional header magic: {magic:#x}')

# Data directories: after optional header (but before section headers)
if magic == 0x10b:  # PE32
    data_dir_offset = optional_header_offset + 96
elif magic == 0x20b:  # PE32+
    data_dir_offset = optional_header_offset + 112
else:
    print(f'Unknown PE magic: {magic:#x}')
    exit(1)

# Export directory is first data directory
export_dir_rva = struct.unpack('<I', data[data_dir_offset:data_dir_offset+4])[0]
export_dir_size = struct.unpack('<I', data[data_dir_offset+4:data_dir_offset+8])[0]
print(f'\nExport directory: RVA={export_dir_rva:#x}, size={export_dir_size}')

# We need the section headers to convert RVA to file offset
section_headers_offset = data_dir_offset + 8 * 16  # 16 data directories

sections = []
for i in range(number_of_sections):
    sh_offset = section_headers_offset + i * 40
    name = data[sh_offset:sh_offset+8].rstrip(b'\x00').decode(errors='replace')
    virtual_size = struct.unpack('<I', data[sh_offset+8:sh_offset+12])[0]
    virtual_address = struct.unpack('<I', data[sh_offset+12:sh_offset+16])[0]  
    size_of_raw_data = struct.unpack('<I', data[sh_offset+16:sh_offset+20])[0]
    pointer_to_raw_data = struct.unpack('<I', data[sh_offset+20:sh_offset+24])[0]
    sections.append({
        'name': name, 'virtual_size': virtual_size, 'virtual_address': virtual_address,
        'raw_size': size_of_raw_data, 'raw_offset': pointer_to_raw_data
    })
    print(f'  Section {name}: VA={virtual_address:#x}, Raw={pointer_to_raw_data:#x}, Size={size_of_raw_data}')

def rva_to_offset(rva):
    """Convert RVA to file offset using section table."""
    for s in sections:
        if s['virtual_address'] <= rva < s['virtual_address'] + s['raw_size']:
            return rva - s['virtual_address'] + s['raw_offset']
    return None

# Read export directory
export_offset = rva_to_offset(export_dir_rva)
if export_offset is None:
    print('Cannot find export directory in file')
    exit(1)

export_flags = struct.unpack('<I', data[export_offset:export_offset+4])[0]
export_timestamp = struct.unpack('<I', data[export_offset+4:export_offset+8])[0]
export_major = struct.unpack('<H', data[export_offset+8:export_offset+10])[0]
export_minor = struct.unpack('<H', data[export_offset+10:export_offset+12])[0]
export_name_rva = struct.unpack('<I', data[export_offset+12:export_offset+16])[0]
export_ordinal_base = struct.unpack('<I', data[export_offset+16:export_offset+20])[0]
export_num_funcs = struct.unpack('<I', data[export_offset+20:export_offset+24])[0]
export_num_names = struct.unpack('<I', data[export_offset+24:export_offset+28])[0]
export_funcs_rva = struct.unpack('<I', data[export_offset+28:export_offset+32])[0]
export_names_rva = struct.unpack('<I', data[export_offset+32:export_offset+36])[0]
export_ordinals_rva = struct.unpack('<I', data[export_offset+36:export_offset+40])[0]

print(f'\nExport table:')
print(f'  Flags: {export_flags:#x}')
print(f'  Timestamp: {export_timestamp}')
print(f'  Version: {export_major}.{export_minor}')
print(f'  Name RVA: {export_name_rva:#x}')
print(f'  Ordinal base: {export_ordinal_base}')
print(f'  Number of functions: {export_num_funcs}')
print(f'  Number of names: {export_num_names}')
print(f'  Functions table RVA: {export_funcs_rva:#x}')
print(f'  Names table RVA: {export_names_rva:#x}')
print(f'  Ordinals table RVA: {export_ordinals_rva:#x}')

# Read the name table (AddressOfNames)
names_table_offset = rva_to_offset(export_names_rva)
ordinals_table_offset = rva_to_offset(export_ordinals_rva)
funcs_table_offset = rva_to_offset(export_funcs_rva)

print(f'\nExport names table offset: {names_table_offset:#x}')
print(f'Ordinals table offset: {ordinals_table_offset:#x}')

# Read all export names
bist_names = []
stata_names = []
other_interesting = []

for i in range(export_num_names):
    name_rva_offset = names_table_offset + i * 4
    name_rva = struct.unpack('<I', data[name_rva_offset:name_rva_offset+4])[0]
    name_offset = rva_to_offset(name_rva)
    if name_offset is None:
        continue
    # Read null-terminated string
    end = data.index(b'\x00', name_offset)
    name = data[name_offset:end].decode(errors='replace')
    
    # Get ordinal and function address
    ordinal_offset = ordinals_table_offset + i * 2
    ordinal = struct.unpack('<H', data[ordinal_offset:ordinal_offset+2])[0]
    func_offset = funcs_table_offset + ordinal * 4
    func_rva = struct.unpack('<I', data[func_offset:func_offset+4])[0]
    
    if 'bist' in name.lower():
        bist_names.append((name, ordinal + export_ordinal_base, func_rva))
    elif 'stata' in name.lower() or name.startswith('_st_') or name.startswith('Stata'):
        stata_names.append((name, ordinal + export_ordinal_base, func_rva))

print(f'\nTotal exports by name: {export_num_names}')
print(f'Functions with ordinal: {export_num_funcs}')
print(f'_bist_ exports: {len(bist_names)}')
print(f'Stata-related exports: {len(stata_names)}')

if bist_names:
    print('\nAll _bist_ exports:')
    for n, ord, rva in sorted(bist_names, key=lambda x: x[0]):
        print(f'  {n}: ordinal={ord}, RVA={rva:#010x}')

print('\nAll Stata-related exports:')
for n, ord, rva in sorted(stata_names, key=lambda x: x[0]):
    print(f'  {n}: ordinal={ord}, RVA={rva:#010x}')

# Check for functions only by ordinal (no name)
# These are functions with entries in AddressOfFunctions but no name entry
named_ordinals = set()
for i in range(export_num_names):
    ordinal_offset = ordinals_table_offset + i * 2
    ordinal = struct.unpack('<H', data[ordinal_offset:ordinal_offset+2])[0]
    named_ordinals.add(ordinal)

for i in range(export_num_funcs):
    if i not in named_ordinals:
        func_offset = funcs_table_offset + i * 4
        func_rva = struct.unpack('<I', data[func_offset:func_offset+4])[0]
        if func_rva != 0:
            print(f'  Ordinal-only export: ordinal={i + export_ordinal_base}, RVA={func_rva:#010x}')
