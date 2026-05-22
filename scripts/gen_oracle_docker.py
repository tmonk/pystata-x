#!/usr/bin/env python3
"""Generate oracle-linux-x86_64.json - tries each section, saves partial output."""
import json, sys, hashlib, os
sys.path.insert(0, '/pystata-x/src')

from pystata_x.sfi._engine import initialize, execute
initialize()

from pystata_x.sfi._core import Data, Macro, Scalar, ValueLabel, Missing
from pystata_x.sfi._core import Characteristic, Datetime, Frame, Matrix, Platform, SFIToolkit

import pystata_x._stata_fast
pystata_x._stata_fast._bist_configured = False

# Setup
for cmd in [
    "sysuse auto, clear",
    "global testglobal = 42",
    "scalar myscalar = 3.14",
    'scalar mystr = "hello"',
    'label define yesno 0 No 1 Yes',
    "label values foreign yesno",
    "matrix mymat = (1,2\\3,4)",
    "matrix rownames mymat = row1 row2",
    "matrix colnames mymat = col1 col2",
    "char _dta[mychar] hello",
    "frame create testframe",
]:
    out, rc = execute(cmd)

o = {}
o["_meta"] = {"generator": "scripts/gen_oracle_docker.py", "dataset": "auto.dta"}

# Collect ALL values
D = Data
o["data"] = {}
try: o["data"]["obs_total"] = D.getObsTotal()
except: o["data"]["obs_total"] = None
try: o["data"]["var_count"] = D.getVarCount()
except: o["data"]["var_count"] = None
try: o["data"]["var_names"] = [D.getVarName(i) for i in range(12)]
except: o["data"]["var_names"] = None
try: o["data"]["var_labels"] = [D.getVarLabel(i) for i in range(12)]
except: o["data"]["var_labels"] = None
try: o["data"]["var_types"] = [str(D.getVarType(i)) for i in range(12)]
except: o["data"]["var_types"] = None
try: o["data"]["var_formats"] = [str(D.getVarFormat(i)) for i in range(12)]
except: o["data"]["var_formats"] = None
try: o["data"]["price_obs0"] = D.get(1, 0)
except: o["data"]["price_obs0"] = None
try: o["data"]["make_obs0"] = D.get(0, 0)
except: o["data"]["make_obs0"] = None
try: o["data"]["max_vars"] = D.getMaxVars()
except: o["data"]["max_vars"] = None

M = Macro
o["macro"] = {}
try: o["macro"]["global_test"] = M.getGlobal("testglobal")
except: pass

S = Scalar
o["scalar"] = {}
try: o["scalar"]["myscalar"] = S.getValue("myscalar")
except: pass
try: o["scalar"]["mystr"] = S.getString("mystr")
except: pass

VL = ValueLabel
o["valuelabel"] = {}
try: o["valuelabel"]["names"] = VL.getNames()
except: pass

C = Characteristic
o["characteristic"] = {}
try: o["characteristic"]["dta_char_mychar"] = C.getDtaChar("mychar")
except: pass

Dt = Datetime
o["datetime"] = {}
try: o["datetime"]["format_0"] = Dt.format(0, "%tc")
except: pass

F = Frame
o["frame"] = {}
try: o["frame"]["frames"] = F.getFrames()
except: pass

Mx = Matrix
o["matrix"] = {}
try: o["matrix"]["mymat_rows"] = Mx.getRowTotal("mymat")
except Exception as e: print(f"Matrix failed: {e}", file=sys.stderr)
try: o["matrix"]["mymat_row_names"] = Mx.getRowNames("mymat")
except Exception as e: print(f"RowNames failed: {e}", file=sys.stderr)
try: o["matrix"]["mymat_at_0_0"] = Mx.getAt("mymat", 0, 0)
except Exception as e: print(f"getAt failed: {e}", file=sys.stderr)

P = Platform
o["platform"] = {}
try: o["platform"]["is_linux"] = P.isLinux()
except: pass

T = SFIToolkit
o["sfitoolkit"] = {}
try: o["sfitoolkit"]["is_valid_name"] = T.isValidName("price")
except: pass

serialised = json.dumps(o, sort_keys=True, default=str).encode()
o["_meta"]["sha256"] = hashlib.sha256(serialised).hexdigest()[:16]

out_path = "/pystata-x/tests/e2e/oracle-linux-x86_64.json"
with open(out_path, "w") as f:
    json.dump(o, f, indent=2, default=str)

print(f"Oracle written to {out_path}", flush=True)
