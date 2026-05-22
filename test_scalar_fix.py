from pystata_x.sfi._engine import initialize, call_double
initialize()
import pystata_x.sfi._engine as eng

eng._LIB.StataSO_Execute(b'sysuse auto, clear')
eng._LIB.StataSO_Execute(b'scalar mystr = "HelloStrScalar"')

import sys
for k in list(sys.modules.keys()):
    if 'core' in k:
        del sys.modules[k]

from pystata_x.sfi._core import Scalar

val = Scalar.getString('mystr')
print('Scalar.getString(' + repr('mystr') + ') = ' + repr(val))
print('Expected: "HelloStrScalar"')
print('Match: ' + str(val == 'HelloStrScalar'))
