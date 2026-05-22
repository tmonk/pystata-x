from pystata_x.sfi._engine import initialize, call_double
initialize()
import pystata_x.sfi._engine as eng

eng._LIB.StataSO_Execute(b'sysuse auto, clear')

import sys
for k in list(sys.modules.keys()):
    if 'core' in k:
        del sys.modules[k]

from pystata_x.sfi._core import Macro

# Test set and get
Macro.setGlobal('testglobal', '42')
result = Macro.getGlobal('testglobal')
print('Global testglobal = ' + repr(result))
print('Expected: "42"')
print('Match: ' + str(result == "42"))

# Test c() values
level = Macro.getGlobal('c(level)')
print('c(level) = ' + repr(level))

# Test non-existent
nonexist = Macro.getGlobal('nonexistent_xyz')
print('nonexistent = ' + repr(nonexist))
print('Expected: ""')
print('Match: ' + str(nonexist == ""))
