"""Search for _bist_ function symbols using PE parsing approach."""
import ctypes
import os

stata_dir = r'C:\Program Files\StataNow19'

# Check for .pyd files specifically (Python C extensions)
pyd_dir = os.path.join(stata_dir, 'utilities', 'Python311')
if os.path.isdir(pyd_dir):
    print('Checking Python extension directory:', pyd_dir)
    for fname in os.listdir(pyd_dir):
        if fname.endswith('.pyd'):
            print(f'  Found .pyd: {fname}')

# Check any .lib files (import libraries)
for fname in os.listdir(stata_dir):
    if fname.endswith('.lib'):
        print(f'Found import library: {fname}')

# Use PE parsing to find _bist_ string refs in the .rdata section
print('\nSearching for _bist_ string references in se-64.dll...')
with open(os.path.join(stata_dir, 'se-64.dll'), 'rb') as f:
    data = f.read()

# Search for _bist_ strings
pos = 0
count = 0
while True:
    pos = data.find(b'_bist_', pos)
    if pos < 0:
        break
    # Read context
    end = data.index(b'\x00', pos)
    name = data[pos:end].decode('ascii', errors='replace')
    if count < 50:
        print(f'  Found at offset {pos:#x}: {name}')
    count += 1
    pos += 1

print(f'Total _bist_ string references: {count}')
if count == 0:
    print('  (No _bist_ strings found in .rdata section)')
else:
    print(f'  (showing first 50)')
