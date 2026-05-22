from pystata_x.sfi._engine import initialize, call_double
initialize()
import pystata_x.sfi._engine as eng

eng._LIB.StataSO_Execute(b'sysuse auto, clear')
eng._LIB.StataSO_Execute(b'label define yesno 0 "No" 1 "Yes"')
eng._LIB.StataSO_Execute(b'label values foreign yesno')

import sys
for k in list(sys.modules.keys()):
    if 'core' in k:
        del sys.modules[k]

from pystata_x.sfi._core import ValueLabel, Data

# Test getNames
names = ValueLabel.getNames()
print('getNames: ' + repr(names))

# Test getLabel
lb0 = ValueLabel.getLabel('yesno', 0)
lb1 = ValueLabel.getLabel('yesno', 1)
print('getLabel(yesno,0): ' + repr(lb0) + ' (expected "No")')
print('getLabel(yesno,1): ' + repr(lb1) + ' (expected "Yes")')

# Test getVarValueLabel for foreign
vl = Data.getVarValueLabel(11)  # foreign is var 12 (1-based), 11 (0-based)
print('getVarValueLabel(11): ' + repr(vl) + ' (expected "yesno")')

# Test getLabels
labels = ValueLabel.getLabels('yesno')
print('getLabels(yesno): ' + repr(labels))

# Test getValues
values = ValueLabel.getValues('yesno')
print('getValues(yesno): ' + repr(values))
