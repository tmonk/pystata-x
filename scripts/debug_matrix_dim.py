"""Debug matrix dimensions on Windows."""
import sys
sys.path.insert(0, 'src')

from pystata_x.sfi._engine import initialize
initialize()

from pystata_x.sfi._strategy import _STRATEGY
from pystata_x.sfi._engine import _LIB, _MEMORY_OFFSETS
import ctypes

# Create a 2x2 matrix
_LIB.StataSO_Execute(b'matrix mymat = (1,2\\3,4)')

# Test rowsof via display 
_LIB.StataSO_Execute(b'display "ROWSOF=" rowsof(mymat)')
print('(display output shown above)')

# Test via gen double (the standard pattern)
_LIB.StataSO_Execute(b'capture drop __px_td')
_LIB.StataSO_Execute(b'gen double __px_td = rowsof(mymat)')
scratch_rva = _MEMORY_OFFSETS.get('scratch_buffer_rva', 0x3b3cc00)
addr = _LIB._handle + scratch_rva
buf = (ctypes.c_double * 1)()
ctypes.memmove(buf, ctypes.c_void_p(addr), 8)
print('rowsof via gen double:', buf[0])

# Test via gen long
_LIB.StataSO_Execute(b'capture drop __px_tl')
_LIB.StataSO_Execute(b'gen long __px_tl = rowsof(mymat)')
ctypes.memmove(buf, ctypes.c_void_p(addr), 8)
print('rowsof via gen long:', buf[0])

# Test via scalar intermediate
_LIB.StataSO_Execute(b'scalar __px_s = rowsof(mymat)')
_LIB.StataSO_Execute(b'capture drop __px_ts')
_LIB.StataSO_Execute(b'gen double __px_ts = scalar(__px_s)')
ctypes.memmove(buf, ctypes.c_void_p(addr), 8)
print('rowsof via scalar:', buf[0])

# Test colsof
_LIB.StataSO_Execute(b'capture drop __px_tc')
_LIB.StataSO_Execute(b'gen double __px_tc = colsof(mymat)')
ctypes.memmove(buf, ctypes.c_void_p(addr), 8)
print('colsof via gen double:', buf[0])

# Test colsof via scalar
_LIB.StataSO_Execute(b'scalar __px_sc = colsof(mymat)')
_LIB.StataSO_Execute(b'capture drop __px_tsc')
_LIB.StataSO_Execute(b'gen double __px_tsc = scalar(__px_sc)')
ctypes.memmove(buf, ctypes.c_void_p(addr), 8)
print('colsof via scalar:', buf[0])

# Read the actual first obs of __px_tl to verify
_LIB.StataSO_Execute(b'capture drop __px_z')
_LIB.StataSO_Execute(b'scalar __px_zv = __px_tl[1]')
_LIB.StataSO_Execute(b'scalar __px_tl = ____px_tl_val')
_LIB.StataSO_Execute(b'gen double __px_z = scalar(__px_zv)')
ctypes.memmove(buf, ctypes.c_void_p(addr), 8)
print('__px_tl[1] value via scalar:', buf[0])

# Alternative approach
_LIB.StataSO_Execute(b'scalar __px_alt = rowsof(mymat)')
_LIB.StataSO_Execute(b'capture drop __px_ta')
_LIB.StataSO_Execute(b'gen double __px_ta = __px_alt')
ctypes.memmove(buf, ctypes.c_void_p(addr), 8)
print('rowsof via scalar=_NOPREFIX_:', buf[0])

# Display 
_LIB.StataSO_Execute(b'matrix list mymat')

print('\nDone')
