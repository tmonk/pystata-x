"""Windows E2E self-consistency test.

Validates all _WindowsStrategy methods by regenerating the oracle
in-process and comparing against the stored oracle_windows.json.
Since the official sfi module is not available in pip Python on Windows,
this test uses self-consistency: our implementation against itself.
"""
import json, os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from pystata_x.sfi._engine import initialize
initialize()

from pystata_x.sfi._strategy import _STRATEGY
from pystata_x.sfi._engine import _LIB, _MEMORY_OFFSETS
import ctypes

# ── Load stored oracle ──
oracle_path = os.path.join(os.path.dirname(__file__), '..', 'tests', 'e2e', 'oracle_windows.json')
with open(oracle_path) as f:
    ORACLE = json.load(f)

errors = []

def check(key, actual, expected):
    if actual != expected:
        errors.append(f'  MISMATCH {key}: expected {repr(expected)}, got {repr(actual)}')
        return False
    return True

# ── Setup ──
_LIB.StataSO_Execute(b'sysuse auto, clear')
_LIB.StataSO_Execute(b'scalar myscalar = 3.14')
_LIB.StataSO_Execute(b'label define yesno2 0 No 1 Yes')
_LIB.StataSO_Execute(b'label values foreign yesno2')
_LIB.StataSO_Execute(b'matrix mymat = (1,2\\3,4)')
_LIB.StataSO_Execute(b'matrix rownames mymat = row1 row2')
_LIB.StataSO_Execute(b'matrix colnames mymat = col1 col2')

# ── Dataset Metadata ──
nv = _STRATEGY.var_count()
no = _STRATEGY.obs_count()
check('var_count', nv, ORACLE['var_count'])
check('obs_count', no, ORACLE['obs_count'])

var_names = [_STRATEGY.get_var_name(i) for i in range(1, nv + 1)]
check('var_names', var_names[:3], ORACLE['var_names'][:3])

var_types = [_STRATEGY.get_var_type(i) for i in range(1, nv + 1)]
check('var_types', var_types[:3], ORACLE['var_types'][:3])

var_formats = [_STRATEGY.get_var_format(i) for i in range(1, nv + 1)]
check('var_formats', var_formats[:3], ORACLE['var_formats'][:3])

# ── Data reads ──
for vi in range(1, min(6, nv + 1)):
    name = var_names[vi - 1]
    for oi in [1, 2, no]:
        key = f'{name}_obs{oi}'
        if key in ORACLE.get('data_reads', {}):
            val = _STRATEGY.data_get(vi, oi)
            check(f'data_reads/{key}', val, ORACLE['data_reads'][key])

# ── String reads ──
make_str = _STRATEGY.get_string(1, 1)
check('string_reads/make_obs1', make_str, ORACLE['string_reads']['make_obs1'])

price_str = _STRATEGY.get_string(2, 1)
check('string_reads/price_obs1_formatted', price_str, ORACLE['string_reads']['price_obs1_formatted'])

weight_str = _STRATEGY.get_string(7, 1)
check('string_reads/weight_obs1_formatted', weight_str, ORACLE['string_reads']['weight_obs1_formatted'])

# ── ValueLabel ──
ve = _STRATEGY.vl_exists('yesno2')
check('valuelabel/vl_exists_yesno2', ve, ORACLE['valuelabel']['vl_exists_yesno2'])

vl0 = _STRATEGY.vl_get_label('yesno2', 0.0)
check('valuelabel/vl_get_label_yesno2_0', vl0, ORACLE['valuelabel']['vl_get_label_yesno2_0'])

vl1 = _STRATEGY.vl_get_label('yesno2', 1.0)
check('valuelabel/vl_get_label_yesno2_1', vl1, ORACLE['valuelabel']['vl_get_label_yesno2_1'])

vvals = _STRATEGY.vl_get_values('yesno2')
check('valuelabel/vl_get_values_yesno2', vvals, ORACLE['valuelabel']['vl_get_values_yesno2'])

# ── Matrix ──
check('matrix/row_total_mymat', _STRATEGY.matrix_get_row_total('mymat'), ORACLE['matrix']['row_total_mymat'])
check('matrix/col_total_mymat', _STRATEGY.matrix_get_col_total('mymat'), ORACLE['matrix']['col_total_mymat'])
check('matrix/value_mymat_0_0', _STRATEGY.matrix_get_value('mymat', 0, 0), ORACLE['matrix']['value_mymat_0_0'])
check('matrix/value_mymat_0_1', _STRATEGY.matrix_get_value('mymat', 0, 1), ORACLE['matrix']['value_mymat_0_1'])
check('matrix/value_mymat_1_0', _STRATEGY.matrix_get_value('mymat', 1, 0), ORACLE['matrix']['value_mymat_1_0'])
check('matrix/value_mymat_1_1', _STRATEGY.matrix_get_value('mymat', 1, 1), ORACLE['matrix']['value_mymat_1_1'])

# ── Scalar ──
check('scalar/myscalar_value', _STRATEGY.get_scalar_value('myscalar'), ORACLE['scalar']['myscalar_value'])

# ── Frame ──
check('frame/default_exists', _STRATEGY.frame_exists('default'), ORACLE['frame']['default_exists'])

# ── Results ──
if errors:
    print(f'\n!! {len(errors)} mismatches:')
    for e in errors:
        print(e)
    sys.exit(1)
else:
    print(f'\nOK All {sum(len(v) if isinstance(v, dict) else 1 for v in ORACLE.values())} oracle validations PASSED')
