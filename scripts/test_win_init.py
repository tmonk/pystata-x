"""Test pystata_x engine initialization on Windows."""
import ctypes
import sys
import os

sys.path.insert(0, r'C:\Users\tom\projects\pystata-x\src')
os.environ['STATA_LIB_PATH'] = r'C:\Program Files\StataNow19\se-64.dll'

print('Importing engine...', flush=True)
from pystata_x.sfi._engine import initialize, _LIB, _MEMORY_OFFSETS

print('Initializing...', flush=True)
initialize()
print('Engine initialized!', flush=True)
print('Memory offsets:', _MEMORY_OFFSETS, flush=True)

# Now test the strategy
from pystata_x.sfi._strategy import _STRATEGY
print('Strategy platform:', _STRATEGY.platform, flush=True)
print('Strategy type:', type(_STRATEGY).__name__, flush=True)

# Test var_count
nv = _STRATEGY.var_count()
print('var_count:', nv, flush=True)

# Load auto and test counts
_LIB.StataSO_Execute(b'sysuse auto, clear')
nv2 = _STRATEGY.var_count()
print('var_count (after auto):', nv2, flush=True)

# Test the Data class
from pystata_x.sfi._core import Data, Macro
print('Macro.getGlobal(c(level)):', Macro.getGlobal('c(level)'), flush=True)

# Test obs_count
from pystata_x.sfi._engine import execute
execute('di "hello from pystata_x on Windows!"')
print('obs_count:', _STRATEGY.obs_count(), flush=True)

# Test a simple data read
print('getVarName(1):', Data.getVarName(1), flush=True)
print('getVarType(1):', Data.getVarType(1), flush=True)

print('All Windows tests passed!', flush=True)
