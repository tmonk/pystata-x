"""Debug frame_exists on Windows."""
import sys
sys.path.insert(0, 'src')

from pystata_x.sfi._engine import initialize
initialize()

from pystata_x.sfi._strategy import _STRATEGY
from pystata_x.sfi._engine import _LIB, _MEMORY_OFFSETS
import ctypes

# Test frame_exists for default
_LIB.StataSO_Execute(b'frame dir')

# Try capture frame exists directly
_LIB.StataSO_Execute(b'capture frame exists default')
_LIB.StataSO_Execute(b'local __px_rc = _rc')
_LIB.StataSO_Execute(b'capture drop __px_tmp')
_LIB.StataSO_Execute(b'gen long __px_tmp = `__px_rc')
scratch_rva = _MEMORY_OFFSETS.get('scratch_buffer_rva', 0x3b3cc00)
addr = _LIB._handle + scratch_rva
buf = (ctypes.c_double * 1)()
ctypes.memmove(buf, ctypes.c_void_p(addr), 8)
print('_rc after frame exists default:', buf[0])

# With scalar intermediate
_LIB.StataSO_Execute(b'capture frame exists default')
_LIB.StataSO_Execute(b'local __px_rc2 = _rc')
_LIB.StataSO_Execute(b'capture scalar __px_s = `__px_rc2')
_LIB.StataSO_Execute(b'capture drop __px_tmp2')
_LIB.StataSO_Execute(b'gen double __px_tmp2 = scalar(__px_s)')
ctypes.memmove(buf, ctypes.c_void_p(addr), 8)
print('_rc via scalar:', buf[0])

# Test via scalar expression
_LIB.StataSO_Execute(b'capture scalar __px_sf = `=cond(frame exists default),1,0)' )  
# Simpler: just capture and test
_LIB.StataSO_Execute(b'capture frame exists default')
_LIB.StataSO_Execute(b'capture gen double __px_sf = (`=_rc == 0)')
ctypes.memmove(buf, ctypes.c_void_p(addr), 8)
print('cond test:', buf[0])

# Direct display
_LIB.StataSO_Execute(b'display "frame exists default = " frame exists default')

# Try using scalar
_LIB.StataSO_Execute(b'scalar __px_test_ex = frame exists default')
_LIB.StataSO_Execute(b'capture drop __px_tmp3')
_LIB.StataSO_Execute(b'gen double __px_tmp3 = scalar(__px_test_ex)')
ctypes.memmove(buf, ctypes.c_void_p(addr), 8)
print('scalar from frame exists:', buf[0])

# What does the Windows strategy do?
result = _STRATEGY.frame_exists('default')
print('_STRATEGY.frame_exists(default):', result)

print('\nDone')
