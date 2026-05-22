from pystata_x.sfi._engine import initialize, call_double
initialize()
import pystata_x.sfi._engine as eng

eng._LIB.StataSO_Execute(b'sysuse auto, clear')

from pystata_x.sfi._core import _init_px_ref, _x86_read_encoded_str
_init_px_ref()

# Test: can we read a value label via local macro expansion?
eng._LIB.StataSO_Execute(b'label define yesno 0 "No" 1 "Yes"')
eng._LIB.StataSO_Execute(b'label values foreign yesno')

# Method: local + $label expansion
eng._LIB.StataSO_Execute(b'local __tmp : label yesno 0')
eng._LIB.StataSO_Execute(b'capture drop __px_vl')
eng._LIB.StataSO_Execute(b'gen str2000 __px_vl = "`__tmp\'"')
nv = int(call_double('_bist_nvar'))
if nv > 12:
    val = _x86_read_encoded_str(lambda o1: '__px_vl[1]', 0)
    print(f'Label yesno,0: {val!r}')
else:
    print('gen failed')

# Method: label yesno 1
eng._LIB.StataSO_Execute(b'local __tmp2 : label yesno 1')
eng._LIB.StataSO_Execute(b'capture drop __px_vl2')
eng._LIB.StataSO_Execute(b'gen str2000 __px_vl2 = "`__tmp2\'"')
val2 = _x86_read_encoded_str(lambda o1: '__px_vl2[1]', 0)
print(f'Label yesno,1: {val2!r}')

# Method: get label name for a variable
eng._LIB.StataSO_Execute(b'local __tmp3 : value label foreign')
eng._LIB.StataSO_Execute(b'capture drop __px_vl3')
eng._LIB.StataSO_Execute(b'gen str2000 __px_vl3 = "`__tmp3\'"')
val3 = _x86_read_encoded_str(lambda o1: '__px_vl3[1]', 0)
print(f'Var label for foreign: {val3!r}')

# List all labels
eng._LIB.StataSO_Execute(b'local __tmp4 : label list')
eng._LIB.StataSO_Execute(b'capture drop __px_vl4')
eng._LIB.StataSO_Execute(b'gen str2000 __px_vl4 = "`__tmp4\'"')
val4 = _x86_read_encoded_str(lambda o1: '__px_vl4[1]', 0)
print(f'All label names: {val4!r}')
