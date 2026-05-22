from pystata_x.sfi._engine import initialize, call_double
initialize()
import pystata_x.sfi._engine as eng

eng._LIB.StataSO_Execute(b'sysuse auto, clear')
eng._LIB.StataSO_Execute(b'label define test1 0 "a" 1 "b"')
eng._LIB.StataSO_Execute(b'label define test2 0 "c" 1 "d"')

from pystata_x.sfi._core import _init_px_ref, _x86_read_encoded_str
_init_px_ref()

# Method 1: direct label list
eng._LIB.StataSO_Execute(b'local __tmp : label list')
eng._LIB.StataSO_Execute(b'capture drop __px_v')
eng._LIB.StataSO_Execute(b'gen str2000 __px_v = "`__tmp\'"')
val = _x86_read_encoded_str(lambda o1: '__px_v[1]', 0)
print(f'Direct label list: {val!r}')

# Method 2: Scan variables for value labels
# quiet forval i=1/12 { local v : value label `i' if `:type `i'' != "str*" }
# but each {} is a separate command, so let's use a simpler approach

# Actually, we can just create list by looking at each variable
# using label list in a single-line command
# 'forvalues i=1/12 { something }' needs to be on one line

# Let's use Stata's foreach with a different approach:
# gen a cumulative string
eng._LIB.StataSO_Execute(b'capture drop __px_names')
eng._LIB.StataSO_Execute(b'gen str2000 __px_names = ""')
nvar = int(call_double('_bist_nvar'))

# Check first 12 variables for value labels
for i in range(1, 13):
    cmd = f'local __tmp : value label {i}'
    eng._LIB.StataSO_Execute(cmd.encode())
    eng._LIB.StataSO_Execute(f'replace __px_names = __px_names + " " + "`__tmp\'" if "`__tmp\'" != "" in 1'.encode())

val2 = _x86_read_encoded_str(lambda o1: '__px_names[1]', 0)
print(f'Scanned label names: {val2!r}')

# Clean up duplicate spaces and split
names = val2.strip().split()
print(f'Parsed names: {names!r}')
