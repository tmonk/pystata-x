from pystata_x.sfi._engine import initialize, call_double
initialize()
import pystata_x.sfi._engine as eng

eng._LIB.StataSO_Execute(b'sysuse auto, clear')
eng._LIB.StataSO_Execute(b'label define test1 0 "a" 1 "b"')
eng._LIB.StataSO_Execute(b'label define test2 0 "c" 1 "d"')

from pystata_x.sfi._core import _init_px_ref, _x86_read_encoded_str
_init_px_ref()

# Try different approaches for label list
# Method 1: direct
eng._LIB.StataSO_Execute(b'local __tmp : label list')
eng._LIB.StataSO_Execute(b'capture drop __px_v')
eng._LIB.StataSO_Execute(b'gen str2000 __px_v = "`__tmp\'"')
val = _x86_read_encoded_str(lambda o1: '__px_v[1]', 0)
print(f'Direct label list: {val!r}')

# Method 2: compound quotes
eng._LIB.StataSO_Execute(b'local __tmp2 `"`: label list\'"\'')
eng._LIB.StataSO_Execute(b'capture drop __px_v2')
eng._LIB.StataSO_Execute(b'gen str2000 __px_v2 = "`__tmp2\'"')
val2 = _x86_read_encoded_str(lambda o1: '__px_v2[1]', 0)
print(f'Compound label list: {val2!r}')

# Method 3: use display to see what label list returns
eng._LIB.StataSO_Execute(b'capture drop __px_v3')
eng._LIB.StataSO_Execute(b'gen str2000 __px_v3 = "`=`: label list'"\'"')
nv = int(call_double('_bist_nvar'))
print(f'nvar after = expression: {nv}')
if nv > 14:
    val3 = _x86_read_encoded_str(lambda o1: '__px_v3[1]', 0)
    print(f'= expression: {val3!r}')

# Method 4: iterate over variables to find labels
eng._LIB.StataSO_Execute(b'local i 1')
eng._LIB.StataSO_Execute(b'capture drop __px_v4')
eng._LIB.StataSO_Execute(b'gen str2000 __px_v4 = ""')
eng._LIB.StataSO_Execute(b'forvalues i = 1/12 {')
eng._LIB.StataSO_Execute(b'  local vl : value label `i\'')
eng._LIB.StataSO_Execute(b'  if `"`vl\'"\' != "" {')
eng._LIB.StataSO_Execute(b'    replace __px_v4 = __px_v4 + " " + "`vl\'" in 1')
eng._LIB.StataSO_Execute(b'  }')
eng._LIB.StataSO_Execute(b'}')
val4 = _x86_read_encoded_str(lambda o1: '__px_v4[1]', 0)
print(f'Iterated label names: {val4!r}')
