from pystata_x.sfi._engine import initialize, call_double
initialize()
import pystata_x.sfi._engine as eng

eng._LIB.StataSO_Execute(b'sysuse auto, clear')
eng._LIB.StataSO_Execute(b'global testglobal = HelloWorld42')

# Test: does $ expand in a display command (sent to output buffer)?
eng._LIB.StataSO_Execute(b'display "$testglobal"')

# Test: does $ expand in a simple local?
eng._LIB.StataSO_Execute(b'local __tmpx "$testglobal"')

# Check if __tmpx has a value by trying to display it
eng._LIB.StataSO_Execute(b'display "`__tmpx\'"')

# Now try to store in a variable
eng._LIB.StataSO_Execute(b'capture drop __px_t')
eng._LIB.StataSO_Execute(b'gen str20 __px_t = "`__tmpx\'"')

from pystata_x.sfi._core import _init_px_ref, _x86_read_encoded_str
_init_px_ref()
val = _x86_read_encoded_str(lambda o1: '__px_t[1]', 0)
print(f'Result: {val!r}')

# Also try with global set WITH quotes
eng._LIB.StataSO_Execute(b'global tg_quoted = "HelloWorld42"')
eng._LIB.StataSO_Execute(b'local __tmpy "$tg_quoted"')
eng._LIB.StataSO_Execute(b'capture drop __px_t2')
eng._LIB.StataSO_Execute(b'gen str20 __px_t2 = "`__tmpy\'"')
val2 = _x86_read_encoded_str(lambda o1: '__px_t2[1]', 0)
print(f'Quoted global: {val2!r}')

# Direct: gen with $ operator
eng._LIB.StataSO_Execute(b'capture drop __px_t3')
eng._LIB.StataSO_Execute(b'gen str20 __px_t3 = "`=strlen("$tg_quoted")'"')
val3 = _x86_read_encoded_str(lambda o1: '__px_t3[1]', 0)
print(f'Direct gen with $: {val3!r}')
