from pystata_x.sfi._engine import initialize, call_double
initialize()
import pystata_x.sfi._engine as eng

eng._LIB.StataSO_Execute(b'sysuse auto, clear')
eng._LIB.StataSO_Execute(b'label define test1 0 "a" 1 "b"')
eng._LIB.StataSO_Execute(b'label define test2 0 "c" 1 "d"')

# Does label list work?
eng._LIB.StataSO_Execute(b'capture noisily label list')
print('label list executed', flush=True)

# Capture into a local
eng._LIB.StataSO_Execute(b'local __tmp : label list')
eng._LIB.StataSO_Execute(b'capture drop __px_l')
eng._LIB.StataSO_Execute(b'gen str2000 __px_l = "`__tmp\':label list\'"')
nv = int(call_double('_bist_nvar'))
print(f'nvar={nv}', flush=True)

from pystata_x.sfi._core import _x86_read_encoded_str
val = _x86_read_encoded_str(lambda o1: '__px_l[1]', 0)
print(f'Label list: {val!r}', flush=True)

# Simpler: store "yesno test1" directly to test encoding works for multi-word strings
eng._LIB.StataSO_Execute(b'capture drop __px_l2')
eng._LIB.StataSO_Execute(b'gen str2000 __px_l2 = "yesno test1 test2"')
val2 = _x86_read_encoded_str(lambda o1: '__px_l2[1]', 0)
print(f'Direct multi-word: {val2!r}', flush=True)
