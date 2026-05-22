"""Generate comprehensive Windows oracle via StataExecute + _WindowsStrategy.

This oracle captures expected values from every SFI method implemented
in _WindowsStrategy. It is used as a regression baseline for Windows
testing, since the official Stata sfi module is not available in pip Python.

Run on Windows: python scripts/gen_win_oracle.py
"""
import ctypes, json, sys, os, math

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from pystata_x.sfi._engine import initialize
initialize()

from pystata_x.sfi._strategy import _STRATEGY
from pystata_x.sfi._engine import _LIB

# ── Setup: load auto dataset, create labels, scalars, matrices ──
_LIB.StataSO_Execute(b'sysuse auto, clear')
_LIB.StataSO_Execute(b'scalar myscalar = 3.14')
_LIB.StataSO_Execute(b'scalar strscalar = "hello"')
_LIB.StataSO_Execute(b'global px_global oracle_test')
_LIB.StataSO_Execute(b'local px_local oracle_local')
_LIB.StataSO_Execute(b'label define yesno2 0 No 1 Yes')
_LIB.StataSO_Execute(b'label values foreign yesno2')
_LIB.StataSO_Execute(b'matrix mymat = (1,2\\3,4)')
_LIB.StataSO_Execute(b'matrix rownames mymat = row1 row2')
_LIB.StataSO_Execute(b'matrix colnames mymat = col1 col2')
_LIB.StataSO_Execute(b'char _dta[test] "dta char value"')
_LIB.StataSO_Execute(b'char price[test2] "var char value"')

o = {}
nv = _STRATEGY.var_count()
no = _STRATEGY.obs_count()

# ── Dataset Metadata ──
o['var_count'] = nv
o['obs_count'] = no
o['var_names'] = [_STRATEGY.get_var_name(i) for i in range(1, nv + 1)]
o['var_types'] = [_STRATEGY.get_var_type(i) for i in range(1, nv + 1)]
o['var_labels'] = [_STRATEGY.get_var_label(i) for i in range(1, nv + 1)]
o['var_formats'] = [_STRATEGY.get_var_format(i) for i in range(1, nv + 1)]
o['var_val_labels'] = [_STRATEGY.get_var_value_label(i) for i in range(1, nv + 1)]

# ── Data reads (numeric) ──
data_reads = {}
for vi in range(1, min(6, nv + 1)):
    name = o['var_names'][vi - 1]
    for oi in [1, 2, no]:
        key = f'{name}_obs{oi}'
        val = _STRATEGY.data_get(oi, vi)
        if val is not None:
            data_reads[key] = val
o['data_reads'] = data_reads

# ── String/Formatted reads ──
string_reads = {}
# String variable (make)
string_reads['make_obs1'] = _STRATEGY.get_string(1, 1)
# Formatted output
string_reads['price_obs1_formatted'] = _STRATEGY.get_string(2, 1)
string_reads['weight_obs1_formatted'] = _STRATEGY.get_string(7, 1)
o['string_reads'] = string_reads

# ── Index lookup ──
index_lookup = {}
for name in ['make', 'price', 'mpg', 'rep78', 'foreign']:
    idx = _STRATEGY.find_var_index(name)
    if idx:
        index_lookup[name] = idx
o['index_lookup'] = index_lookup

# ── Value Labels ──
valuelabel = {}
valuelabel['vl_exists_yesno2'] = _STRATEGY.vl_exists('yesno2')
valuelabel['vl_get_label_yesno2_0'] = _STRATEGY.vl_get_label('yesno2', 0.0)
valuelabel['vl_get_label_yesno2_1'] = _STRATEGY.vl_get_label('yesno2', 1.0)
valuelabel['vl_get_values_yesno2'] = _STRATEGY.vl_get_values('yesno2')
valuelabel['vl_get_labels_yesno2'] = _STRATEGY.vl_get_labels('yesno2')
o['valuelabel'] = valuelabel

# ── Matrix ──
matrix = {}
matrix['row_total_mymat'] = _STRATEGY.matrix_get_row_total('mymat')
matrix['col_total_mymat'] = _STRATEGY.matrix_get_col_total('mymat')
matrix['value_mymat_0_0'] = _STRATEGY.matrix_get_value('mymat', 0, 0)
matrix['value_mymat_0_1'] = _STRATEGY.matrix_get_value('mymat', 0, 1)
matrix['value_mymat_1_0'] = _STRATEGY.matrix_get_value('mymat', 1, 0)
matrix['value_mymat_1_1'] = _STRATEGY.matrix_get_value('mymat', 1, 1)
matrix['row_names_mymat'] = _STRATEGY.matrix_get_row_names('mymat')
matrix['col_names_mymat'] = _STRATEGY.matrix_get_col_names('mymat')
o['matrix'] = matrix

# ── Scalar ──
scalar = {}
scalar['myscalar_value'] = _STRATEGY.get_scalar_value('myscalar')
# Scalar string (set via StataExecute)
scalar['strscalar'] = _STRATEGY.get_scalar_string('strscalar')
o['scalar'] = scalar

# ── Macros ──
macro = {}
macro['px_global'] = _STRATEGY.get_macro_global('px_global')
macro['px_local'] = _STRATEGY.get_macro_local('px_local')
macro['c_level'] = _STRATEGY.macro_expand('c(level)')
macro['pi'] = _STRATEGY.macro_expand('=pi')
o['macro'] = macro

# ── Missing values ──
missing = {}
missing['is_missing_999'] = hasattr(_STRATEGY, 'is_missing') and _STRATEGY.is_missing(-999) if hasattr(_STRATEGY, 'is_missing') else None
o['missing'] = missing

# ── Characteristic ──
char = {}
char['dta_test'] = _STRATEGY.get_dta_char('test')
char['price_test2'] = _STRATEGY.get_var_char('price', 'test2')
o['characteristic'] = char

# ── Frame ──
frame = {}
frame['default_exists'] = _STRATEGY.frame_exists('default')
o['frame'] = frame

# ── Temporaries (tempname) ──
o['tempname'] = _STRATEGY.get_temp_name('px')

# ── Save ──
output_path = os.path.join(os.path.dirname(__file__), '..', 'tests', 'e2e', 'oracle_windows.json')
with open(output_path, 'w') as f:
    json.dump(o, f, indent=2, default=str, ensure_ascii=False)

print(f'OK Windows oracle saved to {output_path} — {len(o)} top-level keys')
for k, v in sorted(o.items()):
    if isinstance(v, dict):
        print(f'  {k}: {len(v)} entries')
    elif isinstance(v, list):
        print(f'  {k}: [{len(v)} items]')
    elif isinstance(v, bool):
        print(f'  {k}: {v}')
    else:
        print(f'  {k}: {repr(v)[:60]}')
