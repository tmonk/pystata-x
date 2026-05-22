"""Test frame exists syntax on Windows."""
import sys, ctypes
sys.path.insert(0, 'src')

from pystata_x.sfi._engine import initialize, _LIB, _MEMORY_OFFSETS
initialize()

def test_cmd(cmd):
    _LIB.StataSO_Execute(cmd)
    
def read_rc():
    _LIB.StataSO_Execute(b'capture drop __px_rcx')
    _LIB.StataSO_Execute(b'capture gen long __px_rcx = `=_rc')
    addr = _LIB._handle + _MEMORY_OFFSETS['scratch_buffer_rva']
    buf = (ctypes.c_double * 1)()
    ctypes.memmove(buf, ctypes.c_void_p(addr), 8)
    return buf[0]

# Try various frame exists syntaxes
for cmd in [
    b'capture frame exists default',
    b'capture frame exists default',
    b'capture frame exists',
    b'capture confirm frame default',
    b'capture framexists default',
]:
    _LIB.StataSO_Execute(cmd)
    rc = read_rc()
    print(f'Command: {cmd.decode(errors="replace")!r} -> rc={rc}')

# Also try with noisily to see error message  
_LIB.StataSO_Execute(b'frame exists default')
# Check if the command failed (no capture = runtime error)
print('(uncaptured frame exists default might have errored)')
