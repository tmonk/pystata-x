"""Generate Windows oracle via Stata's Python integration (stata -q)."""
import ctypes, json, sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))

from pystata_x.sfi._engine import initialize
initialize()

from pystata_x.sfi._strategy import _STRATEGY
from pystata_x.sfi._engine import _LIB

_LIB.StataSO_Execute(b'sysuse auto, clear')
_LIB.StataSO_Execute(b'scalar myscalar = 3.14')
_LIB.StataSO_Execute(b'label define yesno 0 No 1 Yes')
_LIB.StataSO_Execute(b'label values foreign yesno')
_LIB.StataSO_Execute(b'matrix mymat = (1,2\\3,4)')
_LIB.StataSO_Execute(b'matrix rownames mymat = row1 row2')
_LIB.StataSO_Execute(b'matrix colnames mymat = col1 col2')

o = {}

# Data
o['obs_total'] = _STRATEGY.obs_count()
o['var_count'] = _STRATEGY.var_count()
o['var_names'] = [_STRATEGY.get_var_name(i) for i in range(1, 13)]
o['var_labels'] = [_STRATEGY.get_var_label(i) for i in range(1, 13)] if hasattr(_STRATEGY, 'get_var_label') else []
o['var_types'] = [hex(_STRATEGY.get_var_type(i)) for i in range(1, 13)]

# Sample data values
data_samples = {}
for var_idx in range(1, min(6, o['var_count'] + 1)):
    for obs_idx in [1, 2, 74]:
        key = f'var{var_idx}_obs{obs_idx}'
        val = _STRATEGY.data_get(obs_idx, var_idx)
        if val is not None:
            data_samples[key] = val
o['data_samples'] = data_samples

# Save
output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tests', 'e2e', 'oracle_windows.json')
os.makedirs(os.path.dirname(output_path), exist_ok=True)
with open(output_path, 'w') as f:
    json.dump(o, f, indent=2, default=str)

print(f'Windows oracle saved to {output_path}')
print(f'Sample data: {json.dumps(data_samples)}')
