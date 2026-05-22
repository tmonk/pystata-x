"""Debug frame exists rc capture issue."""
import sys
sys.path.insert(0, 'src')
from pystata_x.sfi._engine import initialize
initialize()
from pystata_x.sfi._engine import _LIB
from pystata_x.sfi._strategy import _STRATEGY
from pystata_x.sfi._engine import _MEMORY_OFFSETS
import ctypes

# Test frame change for a non-existent frame
_LIB.StataSO_Execute(b'capture frame change nonexist')
_LIB.StataSO_Execute(b'local __px_rc = _rc')
_LIB.StataSO_Execute(b'capture drop __px_tmp')
_LIB.StataSO_Execute(b'capture gen long __px_tmp = `__px_rc')

addr = _LIB._handle + _MEMORY_OFFSETS['scratch_buffer_rva']
buf = (ctypes.c_double * 1)()
ctypes.memmove(buf, ctypes.c_void_p(addr), 8)
print('rc for nonexist:', buf[0])

# Try capturing _rc directly
_LIB.StataSO_Execute(b'capture frame change nonexist2')
_LIB.StataSO_Execute(b'local __px_rc2 = _rc')
# Don't use gen, use display
_LIB.StataSO_Execute(b'capture drop __px_tmp2')
_LIB.StataSO_Execute(b'gen double __px_tmp2 = `__px_rc2')
ctypes.memmove(buf, ctypes.c_void_p(addr), 8)
print('rc for nonexist2 via gen double:', buf[0])

# Use scalar intermediate
_LIB.StataSO_Execute(b'capture frame change willnotexist')
_LIB.StataSO_Execute(b'scalar __px_rc3 = _rc')
_LIB.StataSO_Execute(b'capture drop __px_tmp3')
_LIB.StataSO_Execute(b'gen double __px_tmp3 = scalar(__px_rc3)')
ctypes.memmove(buf, ctypes.c_void_p(addr), 8)
print('rc via scalar intermediate:', buf[0])

# The problem might be that even for non-existent frames, frame change 
# somehow works or doesn't fail. Let me try without capture:
_LIB.StataSO_Execute(b'frame change truly_nonexistent')
print('(may have errored above)')

# Try frame exists (the official command)
_LIB.StataSO_Execute(b'capture frame exists default')
_LIB.StataSO_Execute(b'scalar __px_r4 = _rc')
_LIB.StataSO_Execute(b'capture drop __px_tmp4')
_LIB.StataSO_Execute(b'gen double __px_tmp4 = scalar(__px_r4)')
ctypes.memmove(buf, ctypes.c_void_p(addr), 8)
print('frame exists default rc:', buf[0])

_LIB.StataSO_Execute(b'capture frame exists nonexistxyz')
_LIB.StataSO_Execute(b'scalar __px_r5 = _rc')
_LIB.StataSO_Execute(b'capture drop __px_tmp5')
_LIB.StataSO_Execute(b'gen double __px_tmp5 = scalar(__px_r5)')
ctypes.memmove(buf, ctypes.c_void_p(addr), 8)
print('frame exists nonexistxyz rc:', buf[0])

print('\nDone')
