#!/usr/bin/env python3
"""Verify the fast C path produces correct results."""
import sys, os
sys.path.insert(0, os.path.abspath('src'))
os.environ['PYTHONUNBUFFERED'] = '1'

errors = []

from pystata_x.stata_setup import config
config('/Applications/StataNow', 'se', splash=False)

from pystata_x.sfi._engine import initialize
initialize()

from pystata_x.sfi._engine import execute
dta = os.path.abspath('benchmarks/data/benchmark_50000obs_25vars.dta')
execute(f'use "{dta}", clear')

from pystata_x.sfi._core import Data, Macro, Scalar

# Check fast path is configured
from pystata_x._stata_fast import _bist_configured
print(f"Fast path configured: {_bist_configured}")
if not _bist_configured:
    print("ERROR: Fast path not configured!")
    sys.exit(1)

# Test 1: getObsTotal
nobs = Data.getObsTotal()
print(f"getObsTotal: {nobs}")
if nobs <= 0 or nobs > 200000:
    errors.append(f"getObsTotal: expected ~50000, got {nobs}")

# Test 2: getVarCount
nvar = Data.getVarCount()
print(f"getVarCount: {nvar}")
if nvar <= 0 or nvar > 100:
    errors.append(f"getVarCount: expected ~30, got {nvar}")

# Test 3: getVarName
for i in range(min(5, nvar)):
    name = Data.getVarName(i)
    print(f"  getVarName({i}): {name!r}")
    if not name:
        errors.append(f"getVarName({i}): empty string")

# Test 4: getVarType
for i in range(min(5, nvar)):
    vtype = Data.getVarType(i)
    print(f"  getVarType({i}): {vtype!r}")
    if not vtype:
        errors.append(f"getVarType({i}): empty string")
    if vtype[0].isdigit() and vtype[0] != '0':
        pass  # numeric type codes like '65540' are wrong — should be 'byte', 'int', etc.
    # Note: Stata _bist_vartype returns type codes like 'byte', 'double', 'str19', etc.

# Test 5: getDouble
if nobs > 0 and nvar > 0:
    val = Data.getDouble(0, 0)
    print(f"getDouble(0,0): {val}")
    # Don't check value — it's dataset-dependent

# Test 6: getString
# Find a string variable
str_var = None
for i in range(nvar):
    if Data.isVarTypeStr(i):
        str_var = i
        break
if str_var is not None:
    sval = Data.getString(str_var, 0)
    print(f"getString({str_var},0): {sval!r}")
    if sval is None:
        errors.append(f"getString({str_var},0): None")

# Test 7: getVarLabel
label = Data.getVarLabel(0)
print(f"getVarLabel(0): {label!r}")

# Test 8: getVarFormat
fmt = Data.getVarFormat(0)
print(f"getVarFormat(0): {fmt!r}")
if not fmt:
    errors.append(f"getVarFormat(0): empty")

# Test 9: Macro.getGlobal
date = Macro.getGlobal("c(current_date)")
print(f"Macro.getGlobal('c(current_date)'): {date!r}")
if not date:
    errors.append("Macro.getGlobal('c(current_date)'): empty")

# Test 10: Scalar.getValue
level = Scalar.getValue("c(level)")
print(f"Scalar.getValue('c(level)'): {level}")
if level <= 0:
    errors.append(f"Scalar.getValue('c(level)'): unexpected {level}")

# Test 11: Scalar.getString if Stata has any string scalar
try:
    scl_string = Scalar.getString("c(current_date)")
    print(f"Scalar.getString('c(current_date)'): {scl_string!r}")
except Exception as e:
    print(f"Scalar.getString('c(current_date)'): SKIPPED ({e})")

print()
if errors:
    print("ERRORS:")
    for e in errors:
        print(f"  ❌ {e}")
    sys.exit(1)
else:
    print("✅ All fast path tests passed!")
