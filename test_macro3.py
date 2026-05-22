from pystata_x.sfi._engine import initialize, call_double
initialize()
import pystata_x.sfi._engine as eng

eng._LIB.StataSO_Execute(b'sysuse auto, clear')
eng._LIB.StataSO_Execute(b'global testglobal = HelloWorld42')
eng._LIB.StataSO_Execute(b'global tg2 = "SomeValue"')

from pystata_x.sfi._core import _init_px_ref, _x86_read_encoded_str
_init_px_ref()

# Method 6: with $tg2 (short name) - already works
# Now test different syntaxes for testglobal
for method_name, cmd in [
    ('= "$testglobal"', b'local __tmp = "$testglobal"'),
    ('= `${testglobal}\'', b'local __tmp = "${testglobal}"'),
    ('= `"$testglobal"\'', b'local __tmp = `"$testglobal"\'"'),
    (': copy global testglobal', b'local __tmp : copy global testglobal'),
    (': macro global testglobal', b'local __tmp : macro global testglobal'),
]:
    eng._LIB.StataSO_Execute(cmd)
    eng._LIB.StataSO_Execute(b'capture drop __px_t')
    eng._LIB.StataSO_Execute(b'gen str20 __px_t = "`__tmp\'"')
    val = _x86_read_encoded_str(lambda o1: '__px_t[1]', 0)
    print(f'{method_name}: {val!r}')
