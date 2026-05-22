#!/usr/bin/env python3
"""Generate oracle-linux-x86_64.json from within Docker.

Usage: docker exec pystata-x-persist /pystata-x/scripts/gen_oracle_docker.py
"""
import json, sys, hashlib, os
sys.path.insert(0, '/pystata-x/src')

from pystata_x.sfi._engine import initialize, execute
initialize()

from pystata_x.sfi._core import Data, Macro, Scalar, ValueLabel, Missing
from pystata_x.sfi._core import Characteristic, Datetime, Frame, Matrix, Platform, SFIToolkit

# C fast path corrupts tsmat state on x86_64 (pool-header patch), disable it
import pystata_x._stata_fast
pystata_x._stata_fast._bist_configured = False

# ── Setup ────────────────────────────────────────────────────────
execute("sysuse auto, clear")
execute("global testglobal = 42")
execute("scalar myscalar = 3.14")
execute('scalar mystr = "hello"')
execute('label define yesno 0 No 1 Yes')
execute("label values foreign yesno")
execute("matrix mymat = (1,2\\3,4)")
execute("matrix rownames mymat = row1 row2")
execute("matrix colnames mymat = col1 col2")
execute("char _dta[mychar] hello")
execute("frame create testframe")

o = {}
o["_meta"] = {
    "generator": "scripts/gen_oracle_docker.py",
    "stata_version": "StataNow 19 SE (Docker x86_64)",
    "dataset": "auto.dta",
}

# ── Data ─────────────────────────────────────────────────────────
D = Data
o["data"] = {
    "obs_total": D.getObsTotal(),
    "var_count": D.getVarCount(),
    "var_names": [D.getVarName(i) for i in range(12)],
    "var_labels": [D.getVarLabel(i) for i in range(12)],
    "var_types": [str(D.getVarType(i)) for i in range(12)],
    "var_formats": [str(D.getVarFormat(i)) for i in range(12)],
    "price_obs0": D.get(1, 0),
    "price_obs73": D.get(1, 73),
    "mpg_obs0": D.get(2, 0),
    "make_obs0": D.get(0, 0),
    "make_obs1": D.get(0, 1),
    "var_index_price": D.getVarIndex("price"),
    "is_alias_0": D.isAlias(0),
    "is_var_type_str_list": [D.isVarTypeStr(i) for i in range(12)],
    "max_str_length": D.getMaxStrLength(),
    "max_vars": D.getMaxVars(),
    "formatted_price_obs0": D.getFormattedValue(1, 0, False),
    "formatted_foreign_obs0": D.getFormattedValue(11, 0, True),
}

# ── Macro ────────────────────────────────────────────────────────
M = Macro
o["macro"] = {
    "global_level": M.getGlobal("c(level)"),
    "global_test": M.getGlobal("testglobal"),
    "global_nonexistent": M.getGlobal("nonexistent_xyz"),
}

# ── Scalar ───────────────────────────────────────────────────────
S = Scalar
o["scalar"] = {
    "myscalar": S.getValue("myscalar"),
    "mystr": S.getString("mystr"),
}

# ── ValueLabel ───────────────────────────────────────────────────
VL = ValueLabel
o["valuelabel"] = {
    "names": VL.getNames(),
    "foreign_label_0": VL.getLabel("yesno", 0),
    "foreign_label_1": VL.getLabel("yesno", 1),
    "foreign_var_vl": VL.getVarValueLabel(11),
    "yesno_labels": VL.getLabels("yesno"),
    "yesno_values": VL.getValues("yesno"),
}

# ── Missing ──────────────────────────────────────────────────────
Mi = Missing
o["missing"] = {
    "is_missing_dot": Mi.isMissing(Mi.getValue()),
    "is_missing_0": Mi.isMissing(0.0),
    "is_missing_42": Mi.isMissing(42.0),
    "parse_is_missing_dot": Mi.parseIsMissing("."),
    "parse_is_missing_0": Mi.parseIsMissing("0"),
    "missing_value": Mi.getValue(),
    "missing_a": Mi.getMissing(Mi.getValue(".a")),
    "missing_z": Mi.getMissing(Mi.getValue(".z")),
}

# ── Characteristic ───────────────────────────────────────────────
C = Characteristic
o["characteristic"] = {
    "dta_char_mychar": C.getDtaChar("mychar"),
    "dta_char_nonexistent": C.getDtaChar("nonexistent"),
}

# ── Datetime ─────────────────────────────────────────────────────
Dt = Datetime
o["datetime"] = {
    "format_0_date": Dt.format(0, "%tc"),
    "format_0_clock": Dt.format(0, "%tC"),
}

# ── Frame ────────────────────────────────────────────────────────
F = Frame
o["frame"] = {
    "cwf": F.getCWF(),
    "frame_count": F.getFrameCount(),
    "all_frames": F.getFrames(),
}

# ── Matrix ───────────────────────────────────────────────────────
Mx = Matrix
o["matrix"] = {
    "mymat_rows": Mx.getRowTotal("mymat"),
    "mymat_cols": Mx.getColTotal("mymat"),
    "mymat_row_names": Mx.getRowNames("mymat"),
    "mymat_col_names": Mx.getColNames("mymat"),
    "mymat_get": Mx.get("mymat"),
    "mymat_at_0_0": Mx.getAt("mymat", 0, 0),
    "mymat_at_0_1": Mx.getAt("mymat", 0, 1),
}

# ── Platform ─────────────────────────────────────────────────────
P = Platform
o["platform"] = {
    "is_windows": P.isWindows(),
    "is_mac": P.isMac(),
    "is_unix": P.isUnix(),
    "is_linux": P.isLinux(),
    "is_solaris": P.isSolaris(),
}

# ── SFIToolkit ───────────────────────────────────────────────────
T = SFIToolkit
o["sfitoolkit"] = {
    "is_valid_name": T.isValidName("price"),
    "is_valid_name_bad": T.isValidName("123bad"),
    "abbrev_price": T.abbrev("price", 5),
    "format_value": T.formatValue(3.14159, "%9.2f"),
    "get_real_of_string_42": T.getRealOfString("42"),
    "get_real_of_string_foo": T.getRealOfString("foo"),
    "make_var_name": T.makeVarName("my var name"),
    "str_to_name": T.strToName("hello world"),
}

# ── Hash ─────────────────────────────────────────────────────────
serialised = json.dumps(o, sort_keys=True, default=str).encode()
o["_meta"]["sha256"] = hashlib.sha256(serialised).hexdigest()[:16]

out_path = "/pystata-x/tests/e2e/oracle-linux-x86_64.json"
with open(out_path, "w") as f:
    json.dump(o, f, indent=2, default=str)

print(f"Oracle written to {out_path}")
print(f"  hash: {o['_meta']['sha256']}")
print(f"  sections: {[k for k in o if not k.startswith('_')]}")
