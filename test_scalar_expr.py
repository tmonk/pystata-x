from pystata_x.sfi._engine import initialize, call_double
initialize()
import pystata_x.sfi._engine as eng

eng._LIB.StataSO_Execute(b'sysuse auto, clear')
eng._LIB.StataSO_Execute(b'scalar mystr = "HelloStrScalar"')

from pystata_x.sfi._core import _init_px_ref
_init_px_ref()

# Create source var and encoding var
eng._LIB.StataSO_Execute(b'capture drop __px_ss')
eng._LIB.StataSO_Execute(b'gen str2000 __px_ss = scalar(mystr)')
eng._LIB.StataSO_Execute(b'capture drop __px_s')
eng._LIB.StataSO_Execute(b'gen double __px_s = .')
nv = int(call_double('_bist_nvar'))
print('nvar: ' + str(nv), flush=True)

# Read __px_ss[1] directly via di to see its content
eng._LIB.StataSO_Execute(b'di __px_ss[1]')
print('di done', flush=True)

# Simple encoding test: first char
eng._LIB.StataSO_Execute(b'replace __px_s = cond(substr(__px_ss[1], 1, 1) == "", 0, 65)')
raw = call_double('_bist_data', 1, nv)
print('Simple encoding: ' + str(raw), flush=True)

# Full first chunk
terms = []
for i in range(6):
    pos = i + 1
    pow256 = 256 ** i
    terms.append(f'cond(substr(__px_ss[1], {pos}, 1) == "", 0, (strpos(__px_ref[1], substr(__px_ss[1], {pos}, 1)) + 31) * {pow256})')
expr = ' + '.join(terms)
eng._LIB.StataSO_Execute(f'replace __px_s = {expr}'.encode())
raw2 = call_double('_bist_data', 1, nv)
print('Full encoding: ' + str(raw2), flush=True)

if raw2 and raw2 > 0:
    raw_int = int(raw2)
    chars = []
    for i in range(6):
        b = (raw_int >> (i * 8)) & 0xFF
        if b == 0:
            break
        chars.append(b)
    result = bytes(chars).decode('latin-1', errors='replace')
    print('Decoded: ' + repr(result), flush=True)
