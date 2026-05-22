"""Debug tempname approach on Windows."""
import sys
sys.path.insert(0, 'src')
from pystata_x.sfi._engine import initialize
initialize()
from pystata_x.sfi._engine import _LIB
from pystata_x.sfi._strategy import _STRATEGY

# Test step by step
# 1. Can we create a local macro with a value?
r = _LIB.StataSO_Execute(b'capture local __px_tn : di "px" + string(floor(runiform()*1e12))')
print('Step 1 rc (local : di):', r)

# 2. Read the local via _read_local_macro
result = _STRATEGY._read_local_macro('__px_tn')
print('Step 2 read_local_macro:', repr(result))

# 3. Try simpler approach: just use a fixed string
_LIB.StataSO_Execute(b'capture local __px_simple : di "px"')
result2 = _STRATEGY._read_local_macro('__px_simple')
print('Step 3 simple local:', repr(result2))

# 4. Try without capture
_LIB.StataSO_Execute(b'local __px_no_cap : di "test_px"')
result3 = _STRATEGY._read_local_macro('__px_no_cap')
print('Step 4 no capture:', repr(result3))

# 5. Direct gen from quoted string
_LIB.StataSO_Execute(b'capture drop __px_t2')
_LIB.StataSO_Execute(b'gen str2000 __px_t2 = "test_string"')
result4 = _STRATEGY.read_encoded_str('__px_t2[1]', obs=1)
print('Step 5 direct gen string:', repr(result4))

# 6. Use just scalar (gen vs dataset issue?)
# Check if we have obs
_LIB.StataSO_Execute(b'capture drop __px_n')
_LIB.StataSO_Execute(b'gen long __px_n = _N')
result5 = _STRATEGY._scratch_read_double()
print('Step 6 _N:', result5)

# 7. Try the tempname approach from X86
_LIB.StataSO_Execute(b'local __tmp : di "px" + string(floor(runiform()*1e12))')
print('Step 7 local set rc:')

# Read back
result6 = _STRATEGY._read_local_macro('__tmp')
print('Step 7 read back:', repr(result6))

print('\nDone')
