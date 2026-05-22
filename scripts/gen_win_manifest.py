"""Generate Windows manifest using extended framework."""
import json
import sys

# Ensure framework is importable
sys.path.insert(0, r'C:\Users\tom\projects\pystata-x\src\pystata-analyzer\src')

print('Importing StataBinary...', flush=True)
from pystata_analyzer import StataBinary

print('Creating binary analyzer...', flush=True)
b = StataBinary(r'C:\Program Files\StataNow19\se-64.dll')

print('Running static analysis...', flush=True)
b.analyze()
print('Done.', flush=True)

print('Calling pe_discover_memory_layout...', flush=True)
try:
    mem = b.pe_discover_memory_layout()
    print('Memory discovery result:', json.dumps(mem, indent=2), flush=True)
except Exception as e:
    import traceback
    print('Error:', e, flush=True)
    traceback.print_exc()
    mem = {}

# Store discovered offsets so manifest includes them
if mem:
    b._memory_offsets.update(mem)

print('Generating manifest...', flush=True)
m = b.generate_manifest()
print('Manifest generated.', flush=True)

# Save to standard location
manifest_dir = r'C:\Users\tom\projects\pystata-x\src\pystata_x\sfi\manifests'
import os
os.makedirs(manifest_dir, exist_ok=True)
path = os.path.join(manifest_dir, 'manifest-windows-x86_64.json')
with open(path, 'w') as f:
    json.dump(m, f, indent=2)
print(f'Saved to {path}', flush=True)
print('Done.', flush=True)
