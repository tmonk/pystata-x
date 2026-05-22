from pystata_x.sfi._engine import initialize, call_double
initialize()
import pystata_x.sfi._engine as eng

eng._LIB.StataSO_Execute(b'sysuse auto, clear')
eng._LIB.StataSO_Execute(b'scalar mystr = "HelloStrScalar"')

from pystata_x.sfi._core import _init_px_ref, _x86_read_encoded_str
_init_px_ref()
print('ref done', flush=True)

# Create source var
eng._LIB.StataSO_Execute(b'capture drop __px_ss')
eng._LIB.StataSO_Execute(b'gen str2000 __px_ss = scalar(mystr)')
print('src created', flush=True)

# Do EXACTLY what _x86_read_encoded_str does
# Step 1: check __px_ref
from pystata_x.sfi._engine import _read_var_name_x86 as _rvn
nv = int(call_double('_bist_nvar'))
print(f'nvar={nv}', flush=True)
_pxr = _rvn(nv - 1) if nv > 0 else None
print(f'last var: {_pxr}', flush=True)

# Step 2: create __px_s
eng._LIB.StataSO_Execute(b'capture drop __px_s')
eng._LIB.StataSO_Execute(b'gen double __px_s = .')
idx = int(call_double('_bist_nvar'))
print(f'idx={idx}', flush=True)

# Step 3: build encoding for first chunk
src = '__px_ss[1]'
terms = []
for i in range(6):
    pos = i + 1
    pow256 = 256 ** i
    terms.append(f'cond(substr({src}, {pos}, 1) == "", 0, (strpos(__px_ref[1], substr({src}, {pos}, 1)) + 31) * {pow256})')
expr = ' + '.join(terms)
print(f'expr ({len(expr)} chars): {expr[:100]}...', flush=True)

# Step 4: execute replace
cmd = f'replace __px_s = {expr}'
eng._LIB.StataSO_Execute(cmd.encode())
print('replace done', flush=True)

# Step 5: read
raw = call_double('_bist_data', 1, idx)
print(f'raw: {raw}', flush=True)

if raw and raw > 0:
    raw_int = int(raw)
    chars = []
    for i in range(6):
        b = (raw_int >> (i * 8)) & 0xFF
        if b == 0:
            break
        chars.append(b)
    result = bytes(chars).decode('latin-1', errors='replace')
    print(f'result: {result!r}', flush=True)
else:
    print('raw is 0 or None', flush=True)
