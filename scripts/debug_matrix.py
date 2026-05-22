"""Debug matrix operations on Windows."""
import sys
sys.path.insert(0, 'src')

from pystata_x.sfi._engine import initialize
initialize()

from pystata_x.sfi._strategy import _STRATEGY
from pystata_x.sfi._engine import _LIB
from pystata_x.sfi._manifest import _MEMORY_OFFSETS
import ctypes

_LIB.StataSO_Execute(b'sysuse auto, clear')

# Create matrix
_LIB.StataSO_Execute(b'matrix mymat = (1,2\\3,4)')
_LIB.StataSO_Execute(b'matrix rownames mymat = row1 row2')
_LIB.StataSO_Execute(b'matrix colnames mymat = col1 col2')

# Direct Stata commands
_LIB.StataSO_Execute(b'matrix list mymat')
_LIB.StataSO_Execute(b'gen double __px_t = rowsof(mymat)')

# Read scratch
scratch_rva = _MEMORY_OFFSETS.get('scratch_buffer_rva', 0x3b3cc00)
addr = _LIB._handle + scratch_rva
buf = (ctypes.c_double * 1)()
ctypes.memmove(buf, ctypes.c_void_p(addr), 8)
print('rowsof from gen double:', buf[0])

_LIB.StataSO_Execute(b'gen double __px_c = colsof(mymat)')
ctypes.memmove(buf, ctypes.c_void_p(addr), 8)
print('colsof from gen double:', buf[0])

# Try gen long
_LIB.StataSO_Execute(b'gen long __px_r = rowsof(mymat)')
ctypes.memmove(buf, ctypes.c_void_p(addr), 8)
print('rowsof from gen long:', buf[0])

# Try display
_LIB.StataSO_Execute(b'local __px_rs : display rowsof(mymat)')
print('local from display done')

# Try scalar
_LIB.StataSO_Execute(b'scalar __px_s = rowsof(mymat)')
_LIB.StataSO_Execute(b'gen double __px_s2 = scalar(__px_s)')
ctypes.memmove(buf, ctypes.c_void_p(addr), 8)
print('rowsof via scalar:', buf[0])

# Try directly in expression
_LIB.StataSO_Execute(b'gen double __px_ex = 2 + 2')  
ctypes.memmove(buf, ctypes.c_void_p(addr), 8)
print('2+2 test:', buf[0])

# Check if matrix exists
_LIB.StataSO_Execute(b'matrix mymat2 = mymat')
print('matrix copy rc: (checked)')

# Try rowsof on matrix with different name
_LIB.StataSO_Execute(b'gen double __px_r2 = rowsof(mymat2)')
ctypes.memmove(buf, ctypes.c_void_p(addr), 8)
print('rowsof(mymat2):', buf[0])

print('\nDone')
