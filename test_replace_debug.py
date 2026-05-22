from pystata_x.sfi._engine import initialize, call_double
initialize()
import pystata_x.sfi._engine as eng

eng._LIB.StataSO_Execute(b'sysuse auto, clear')
eng._LIB.StataSO_Execute(b'scalar mystr = "HelloStrScalar"')

# Create source var
eng._LIB.StataSO_Execute(b'gen str2000 __px_ss = scalar(mystr)')
nv = int(call_double('_bist_nvar'))
print(f'nvar after gen: {nv}', flush=True)

# Verify __px_ss has the value
eng._LIB.StataSO_Execute(b'gen double __px_t = strlen(__px_ss[1])')
nv2 = int(call_double('_bist_nvar'))
val = call_double('_bist_data', 1, nv2)
print(f'strlen(__px_ss[1]) = {val}', flush=True)

# Now test replace __px_t with cond
eng._LIB.StataSO_Execute(b'replace __px_t = cond(substr(__px_ss[1], 1, 1) == "", 0, 65)')
val2 = call_double('_bist_data', 1, nv2)
print(f'cond test on __px_t: {val2}', flush=True)

# Test with a different variable that we KNOW works
eng._LIB.StataSO_Execute(b'gen double __px_u = cond(substr(make[1], 1, 1) == "", 0, 65)')
nv3 = int(call_double('_bist_nvar'))
val3 = call_double('_bist_data', 1, nv3)
print(f'cond on make[1]: {val3} (expected 65)', flush=True)
