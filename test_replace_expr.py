from pystata_x.sfi._engine import initialize, call_double
initialize()
import pystata_x.sfi._engine as eng

eng._LIB.StataSO_Execute(b'sysuse auto, clear')
eng._LIB.StataSO_Execute(b'scalar mystr = "HelloStrScalar"')

from pystata_x.sfi._core import _init_px_ref
_init_px_ref()

# Create source
eng._LIB.StataSO_Execute(b'capture drop __px_ss')
eng._LIB.StataSO_Execute(b'gen str2000 __px_ss = scalar(mystr)')

# Now create __px_s
eng._LIB.StataSO_Execute(b'capture drop __px_s')
eng._LIB.StataSO_Execute(b'gen double __px_s = .')
idx = int(call_double('_bist_nvar'))
print(f'idx={idx}', flush=True)

# Simplest possible replace
eng._LIB.StataSO_Execute(b'replace __px_s = 42')
raw = call_double('_bist_data', 1, idx)
print(f'Simple replace=42: {raw}', flush=True)

# Replace with cond
eng._LIB.StataSO_Execute(b'replace __px_s = cond(substr(__px_ss[1], 1, 1) == "", 0, 65)')
raw2 = call_double('_bist_data', 1, idx)
print(f'cond+substr: {raw2} (expected 65)', flush=True)

# Replace with strpos
eng._LIB.StataSO_Execute(b'replace __px_s = strpos(__px_ref[1], substr(__px_ss[1], 1, 1)) + 31')
raw3 = call_double('_bist_data', 1, idx)
print(f'strpos: {raw3} (expected 72 = H)', flush=True)

# Full expression for first byte (not 6)
eng._LIB.StataSO_Execute(b'replace __px_s = cond(substr(__px_ss[1], 1, 1) == "", 0, (strpos(__px_ref[1], substr(__px_ss[1], 1, 1)) + 31) * 1)')
raw4 = call_double('_bist_data', 1, idx)
print(f'Full single byte: {raw4} (expected 72)', flush=True)

# Full expression for first 6 bytes
terms = []
for i in range(6):
    pos = i + 1
    pow256 = 256 ** i
    terms.append(f'cond(substr(__px_ss[1], {pos}, 1) == "", 0, (strpos(__px_ref[1], substr(__px_ss[1], {pos}, 1)) + 31) * {pow256})')
expr = ' + '.join(terms)
eng._LIB.StataSO_Execute(f'replace __px_s = {expr}'.encode())
raw5 = call_double('_bist_data', 1, idx)
print(f'Full 6 bytes: {raw5}', flush=True)
