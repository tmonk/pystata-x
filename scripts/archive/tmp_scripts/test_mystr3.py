import os, sys, ctypes
os.environ["STATA_LIB_PATH"] = "/usr/local/stata19/libstata-se.so"
import pystata_x.sfi._engine as eng
eng.initialize()
lib = eng._LIB
lib.StataSO_Execute(b"sysuse auto, clear")
print("OK", flush=True)

lib.StataSO_SetOutputBufferSz(65536)
lib.StataSO_ClearOutputBuffer.restype = None

# Create string scalar with quotes
lib.StataSO_ClearOutputBuffer()
rc = lib.StataSO_Execute(b'scalar mystr = "hello"')
print(f"scalar mystr = \"hello\": rc={rc}", flush=True)

# Try _bist_strscalar directly
from pystata_x.sfi._engine import call_string
result = call_string("_bist_strscalar", b"mystr")
print(f"call_string(_bist_strscalar, 'mystr') = {result!r}", flush=True)

# Try C fast path
try:
    import pystata_x._stata_fast as sf
    result2 = sf.get_scalar_str("mystr")
    print(f"fast_path.get_scalar_str('mystr') = {result2!r}", flush=True)
except Exception as e:
    print(f"fast_path error: {e}", flush=True)

# Try display-based
from pystata_x.sfi._x86_display import read_string_scalar, clear_cache
clear_cache()
result3 = read_string_scalar("mystr")
print(f"read_string_scalar('mystr') = {result3!r}", flush=True)

# Also try: maybe the string scalar name has a different convention
lib.StataSO_ClearOutputBuffer()
rc = lib.StataSO_Execute(b'display `"hello"')
buf = lib.StataSO_GetOutputBuffer
buf.restype = ctypes.c_char_p
out = buf()
print(f"display 'hello': rc={rc} out={out.decode()!r}", flush=True)
