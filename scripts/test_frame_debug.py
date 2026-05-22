"""Debug Frame.getFrames."""
import sys
sys.path.insert(0, '/pystata-x/src')
from pystata_x.sfi._engine import initialize, execute
initialize()
from pystata_x.sfi._engine import _LIB
import pystata_x._stata_fast
pystata_x._stata_fast._bist_configured = False

execute("frame create testframe")

# Test the extended macro
rc = _LIB.StataSO_Execute(b'local __tmp : frame dir')
print(f"local __tmp : frame dir -> rc={rc}", flush=True)

# Read the local macro
_LIB.StataSO_Execute(b'capture drop __px_z')
_LIB.StataSO_Execute(b'gen str2000 __px_z = "`__tmp\'"')

from pystata_x.sfi._core import _x86_read_encoded_str, _init_px_ref
_init_px_ref()
r = _x86_read_encoded_str(lambda o: '__px_z[1]', 0, is_dataset=False)
print(f"Read __tmp: {r!r}", flush=True)
