from pystata_x.sfi._engine import initialize, call_double
initialize()
import pystata_x.sfi._engine as eng

eng._LIB.StataSO_Execute(b'sysuse auto, clear')
eng._LIB.StataSO_Execute(b'global tm = "Hello42"')
nv0 = int(call_double('_bist_nvar'))

# Step 1: gen str10 __px_t
eng._LIB.StataSO_Execute(b'gen str10 __px_t = "$tm"')
nv = int(call_double('_bist_nvar'))
print(f'After gen str10: nvar={nv}', flush=True)

# Step 2: drop __px_t  
eng._LIB.StataSO_Execute(b'drop __px_t')
nv = int(call_double('_bist_nvar'))
print(f'After drop: nvar={nv}', flush=True)

# Step 3: gen str10 __px_t again (same name)
eng._LIB.StataSO_Execute(b'gen str10 __px_t = "$tm"')
nv = int(call_double('_bist_nvar'))
print(f'After re-gen str10: nvar={nv}', flush=True)

# Step 4: gen str10 __px_t2 (different name)
eng._LIB.StataSO_Execute(b'gen str10 __px_t2 = "$tm"')
nv = int(call_double('_bist_nvar'))
print(f'After gen str10 __px_t2: nvar={nv}', flush=True)
