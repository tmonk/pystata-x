"""Test new Windows overrides."""
import sys
sys.path.insert(0, 'src')

from pystata_x.sfi._engine import initialize
initialize()

from pystata_x.sfi._strategy import _STRATEGY
from pystata_x.sfi._engine import _LIB

_LIB.StataSO_Execute(b'sysuse auto, clear')
_LIB.StataSO_Execute(b'label define yesno 0 No 1 Yes')
_LIB.StataSO_Execute(b'label values foreign yesno')

print('var_label(12):', repr(_STRATEGY.get_var_label(12)))
print('val_label(12):', repr(_STRATEGY.get_var_value_label(12)))
print('vl_exists(yesno):', _STRATEGY.vl_exists('yesno'))
print('vl_exists(nonexist):', _STRATEGY.vl_exists('nonexist'))
print('vl_get_label(yesno, 0):', repr(_STRATEGY.vl_get_label('yesno', 0.0)))
print('vl_get_label(yesno, 1):', repr(_STRATEGY.vl_get_label('yesno', 1.0)))
print('vl_get_names:', _STRATEGY.vl_get_names())
print('vl_get_values(yesno):', _STRATEGY.vl_get_values('yesno'))
print('vl_get_labels(yesno):', _STRATEGY.vl_get_labels('yesno'))

_LIB.StataSO_Execute(b'matrix mymat = (1,2\\3,4)')
print('matrix_get_row_total(mymat):', _STRATEGY.matrix_get_row_total('mymat'))
print('matrix_get_col_total(mymat):', _STRATEGY.matrix_get_col_total('mymat'))
print('matrix_get_value(mymat,0,0):', _STRATEGY.matrix_get_value('mymat', 0, 0))

# Test var label reading
print('var_label(1):', repr(_STRATEGY.get_var_label(1)))
