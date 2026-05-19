"""SFI API implementation backed by direct _bist_ C function calls.

All SFI data access operations use direct C function pointer calls to
Stata's internal _bist_* functions.  ZERO StataSO_Execute calls for
all data reads AND writes across every SFI surface:
  - Cell data: _bist_data, _bist_sdata, _bist_store, _bist_sstore
  - Variable metadata: _bist_varname, _bist_varlabel, _bist_varformat, etc.
  - Macros: _bist_global, _bist_putglobal
  - Numeric scalars: _bist_numscalar, _stscalsave
  - String scalars: _bist_strscalar, _xgso_newcp_fast_code + _put_xgso_scalar
  - Value labels: _bist_vlexists, _bist_vlmap, _bist_vlsearch, _bist_vldrop
  - Direct memory reads for obs/var counts

StataSO_Execute is ONLY used for the designated command execution API:
  1. SFIToolkit.executeCommand() / SFIToolkit.stata()

Platform dispatch:
  ARM64 (macOS): push+stack convention via _pushint/_pushdbl/_pushstr
  x86_64 (Linux/Windows): direct CFUNCTYPE standard ABI
"""

import ctypes
import logging
import os
import sys
import platform
import math
import warnings
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Any
from pystata_x.sfi._engine import (
    call_int,
    call_double,
    call_string,
    call_void,
    call_store_double,
    call_store_string,
    call_set_scalar,
    call_set_strscalar,
    call_create_valuelabel,
    call_vlmodify,
    read_obs_count,
    read_var_count,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════
# Macro
# ═══════════════════════════════════════════
class Macro:
    @staticmethod
    def getGlobal(name: str) -> str:
        """Get the value of a Stata global macro."""
        return call_string("_bist_global", name.encode())

    @staticmethod
    def setGlobal(name: str, value: str) -> None:
        """Set a Stata global macro."""
        call_int("_bist_putglobal", name.encode(), value.encode())

    @staticmethod
    def delGlobal(name: str) -> None:
        """Delete a Stata global macro by setting it to empty."""
        call_int("_bist_putglobal", name.encode(), b" ")

    @staticmethod
    def getLocal(name: str) -> str:
        """Get the value of a Stata local macro."""
        return call_string("_bist_local", name.encode())

    @staticmethod
    def setLocal(name: str, value: str) -> None:
        """Set a Stata local macro.

        Note: _bist_putglobal with additional "local" mode or _bist_local
        write.  We use call_int directly.
        """
        call_int("_bist_putglobal", name.encode(), value.encode())


# ═══════════════════════════════════════════
# Data
# ═══════════════════════════════════════════
class Data:
    @staticmethod
    def getObsTotal() -> int:
        """Total number of observations in the current dataset."""
        return read_obs_count()

    @staticmethod
    def getVarCount() -> int:
        """Number of variables in the current dataset."""
        return read_var_count()

    @staticmethod
    def getVarName(varno: int) -> str:
        """Get the name of a variable by its Python index (0-based)."""
        return call_string("_bist_varname", varno + 1)

    @staticmethod
    def getVarLabel(varno: int) -> str:
        """Get the label of a variable by its Python index (0-based)."""
        return call_string("_bist_varlabel", varno + 1)

    @staticmethod
    def getVarType(varno: int) -> str:
        """Get the storage type of a Stata variable, e.g. 'str18', 'strL', 'double', 'int', 'byte', 'long', 'float'."""
        return call_string("_bist_vartype", varno + 1)

    @staticmethod
    def getVarIndex(name: str) -> int:
        """Get the 0-based index of a variable by name.

        Raises ValueError if the variable name is not found.
        """
        idx = call_int("_bist_varindex", name.encode())
        if idx is None or idx == 0:
            raise ValueError(f"variable {name!r} not found")
        return idx - 1

    @staticmethod
    def getVarFormat(varno: int) -> str:
        """Get the display format of a variable."""
        return call_string("_bist_varformat", varno + 1)

    @staticmethod
    def setVarFormat(varno: int, fmt: str) -> None:
        """Set the display format of a variable."""
        call_int("_bist_varformat", varno + 1, fmt.encode())

    @staticmethod
    def setVarLabel(varno: int, label: str) -> None:
        """Set the label of a variable."""
        call_int("_bist_varlabel", varno + 1, label.encode())

    @staticmethod
    def getDouble(varno: int, obs: int) -> float:
        """Read a numeric value from a cell."""
        return call_double("_bist_data", obs + 1, varno + 1)

    @staticmethod
    def getString(varno: int, obs: int) -> str:
        """Read a string value from a cell."""
        return call_string("_bist_sdata", obs + 1, varno + 1)

    @staticmethod
    def storeDouble(varno: int, obs: int, val: float) -> None:
        """Write a numeric value to a cell."""
        call_store_double("_bist_store", obs + 1, varno + 1, val)

    @staticmethod
    def storeString(varno: int, obs: int, val: str) -> None:
        """Write a string value to a cell."""
        call_store_string("_bist_sstore", obs + 1, varno + 1, val.encode())

    @staticmethod
    def addObs(n: int = 1) -> None:
        """Add n observations."""
        call_void("_bist_addobs", float(n))

    @staticmethod
    def addVarDouble(name: str) -> int:
        """Add a new double variable."""
        return call_int("_bist_addvar", name.encode(), ord('d'))

    @staticmethod
    def addVarStr(name: str, length: int) -> int:
        """Add a new string variable."""
        return call_int("_bist_addvar", name.encode(), ord('s'), length)

    @staticmethod
    def addVarByte(name: str) -> int:
        """Add a new byte variable."""
        return call_int("_bist_addvar", name.encode(), ord('b'))

    @staticmethod
    def addVarInt(name: str) -> int:
        """Add a new int variable."""
        return call_int("_bist_addvar", name.encode(), ord('i'))

    @staticmethod
    def addVarLong(name: str) -> int:
        """Add a new long variable."""
        return call_int("_bist_addvar", name.encode(), ord('l'))

    @staticmethod
    def addVarFloat(name: str) -> int:
        """Add a new float variable."""
        return call_int("_bist_addvar", name.encode(), ord('f'))

    @staticmethod
    def dropVar(varno: int) -> None:
        """Drop a variable by index."""
        call_void("_bist_dropvar", float(varno + 1))

    @staticmethod
    def renameVar(varno: int, new_name: str) -> None:
        """Rename a variable."""
        call_void("_bist_varrename", float(varno + 1), new_name.encode())

    @staticmethod
    def keepVar(varno: int) -> None:
        """Keep (drop all except) a variable."""
        call_void("_bist_keepvar", float(varno + 1))

    @staticmethod
    def getAt(varno: int, obs: int) -> float:
        """Get the value at (var, obs). Alias for getDouble."""
        return Data.getDouble(varno, obs)

    @staticmethod
    def storeAt(varno: int, obs: int, val: float) -> None:
        """Store a value at (var, obs). Alias for storeDouble."""
        Data.storeDouble(varno, obs, val)

    @staticmethod
    def getVarValueLabel(varno: int) -> str:
        """Get the value label name attached to a variable."""
        return call_string("_bist_varvaluelabel", varno + 1)

    @staticmethod
    def isVarTypeStr(varno: int) -> bool:
        """Check if variable is a string type."""
        r = call_int("_bist_isstrvar", varno + 1)
        return bool(r) if r is not None else False

    @staticmethod
    def isVarTypeNumeric(varno: int) -> bool:
        """Check if variable is a numeric type."""
        r = call_int("_bist_isnumvar", varno + 1)
        return bool(r) if r is not None else False

    @staticmethod
    def getStrVarWidth(varno: int) -> int:
        """Get the string width of a string variable.

        Returns the storage length for string vars (e.g., 18 for str18),
        0 for numeric, and large value (2045) for strL.
        """
        t = Data.getVarType(varno)
        if not t:
            return 0
        if t == 'strL':
            return 2045
        if t.startswith('str'):
            try:
                return int(t[3:])  # e.g. 'str18' -> 18
            except ValueError:
                return 0
        return 0

    @staticmethod
    def getBestType(value: float) -> int:
        """Get the best Stata storage type for a given value.
        Returns 2=byte, 3=int, 4=long, 5=float, 6=double."""
        if math.isnan(value):
            return 6
        av = abs(value)
        if av < 100 and av == int(av):
            if av < 127:
                return 2
            if av < 32767:
                return 3
            return 4
        if av < 1e38:
            return 5
        return 6

    @staticmethod
    def getMaxStrLength() -> int:
        """Get the maximum string length (2045 for Stata SE/MP)."""
        return 2045

    @staticmethod
    def getMaxVars() -> int:
        """Get the maximum variables (32767 for Stata SE/MP)."""
        return 32767

    @staticmethod
    def isAlias(varno: int) -> bool:
        """Check if a variable is an alias via _bist_isalias."""
        r = call_int("_bist_isalias", varno + 1)
        return bool(r) if r is not None else False

    @staticmethod
    def isVarTypeString(varno: int) -> bool:
        """Check if a variable is string type (alias for isVarTypeStr)."""
        return Data.isVarTypeStr(varno)

    @staticmethod
    def isVarTypeStrL(varno: int) -> bool:
        """Check if a variable is a StrL (long string) type."""
        t = Data.getVarType(varno)
        return t == 'strL'

    @staticmethod
    def connect(name: str, obs: int = None) -> 'StrLConnector':
        """Connect to a StrL variable, returning a StrLConnector."""
        from pystata_x.sfi._core import StrLConnector
        var_idx = Data.getVarIndex(name)
        return StrLConnector(var_idx, obs or 0)

    @staticmethod
    def addVarStrL(name: str) -> int:
        """Add a variable of type strL to the current dataset.

        No _bist_*/_bi_st_* function found that creates strL variables.
        _stpy_addvarstrl exists but segfaults via ctypes.
        """
        raise NotImplementedError(
            'addVarStrL: only _stpy_addvarstrl exists (segfaults). '
            'Use SFIToolkit.executeCommand(f"gen strL {name} = \"\"") instead.'
        )

    @staticmethod
    def allocateStrL(sc: 'StrLConnector', size: int, binary: bool = True) -> None:
        """Allocate a strL buffer.

        Only _stpy_allocatestrl exists (segfaults via ctypes).
        No _bist_*/_bi_st_* equivalent found.
        """
        raise NotImplementedError(
            'allocateStrL: only _stpy_allocatestrl exists (segfaults). '
            'No _bist_*/_bi_st_* equivalent found.'
        )

    @staticmethod
    def readBytes(sc: 'StrLConnector', length: int) -> bytes:
        """Read bytes from a StrLConnector."""
        if not isinstance(sc, StrLConnector):
            raise TypeError('sc must be a StrLConnector')
        return sc.readBytes(length)

    @staticmethod
    def writeBytes(sc: 'StrLConnector', b: bytes, off: int = None, length: int = None):
        """Write bytes to a strL cell.

        No _bist_*/_bi_st_* function found for strL writes.
        Only _stpy_storebytes exists (segfaults).
        """
        raise NotImplementedError(
            'writeBytes: only _stpy* functions exist for strL writing, '
            'which segfault via ctypes. No _bist_*/_bi_st_* equivalent found.'
        )

    @staticmethod
    def storeBytes(sc: 'StrLConnector', b: bytes, binary: bool = True):
        """Store bytes in a strL cell.

        No _bist_*/_bi_st_* function found for strL writes.
        Only _stpy_storebytes exists (segfaults).
        """
        raise NotImplementedError(
            'storeBytes: only _stpy* functions exist for strL writing, '
            'which segfault via ctypes. No _bist_*/_bi_st_* equivalent found.'
        )

    @staticmethod
    def getFormattedValue(varno: int, obs: int, bValueLabel: bool = False) -> str:
        """Get a cell's formatted display value (pure Python)."""
        fmt = Data.getVarFormat(varno)
        t = Data.getVarType(varno)
        if t and t.startswith('str'):
            val = Data.getString(varno, obs)
            return val if val else ""
        val = Data.getDouble(varno, obs)
        if math.isnan(val):
            return "."
        if bValueLabel:
            from pystata_x.sfi._core import ValueLabel
            label = Data.getVarValueLabel(varno)
            if label:
                lbl = ValueLabel.getLabel(label, val)
                if lbl:
                    return lbl
        if fmt:
            try:
                return Data._format_value(val, fmt)
            except (ValueError, TypeError):
                pass
        return str(val)

    @staticmethod
    def _format_value(val: float, fmt: str) -> str:
        """Format a numeric value using a Stata-like format."""
        fmt = fmt.strip()
        if not fmt:
            return str(val)
        stype = 'g'
        width = 8
        decimals = 2
        if '%' in fmt:
            fmt = fmt[fmt.index('%')+1:]
        import re
        m = re.match(r'(\d+)(?:\.(\d+))?([a-zA-Z]?)', fmt)
        if m:
            width = int(m.group(1))
            if m.group(2):
                decimals = int(m.group(2))
            if m.group(3):
                stype = m.group(3)
        try:
            if stype == 'f':
                return f"{val:{width}.{decimals}f}"
            elif stype == 'e':
                return f"{val:{width}.{decimals}e}"
            elif stype in ('g', ''):
                return f"{val:{width}.{decimals}g}"
        except (ValueError, TypeError):
            pass
        return str(val)

    @staticmethod
    def setObsTotal(nobs: int) -> None:
        """Set total observations via addObs with the delta."""
        current = Data.getObsTotal()
        delta = nobs - current
        if delta > 0:
            Data.addObs(delta)
        elif delta < 0:
            call_void("_bist_addobs", float(delta))

    @staticmethod
    def _get_pandas_available() -> bool:
        """Check if pandas is available."""
        try:
            import pandas as pd
            return True
        except ImportError:
            return False

    @staticmethod
    def _get_numpy_available() -> bool:
        """Check if numpy is available."""
        try:
            import numpy as np
            return True
        except ImportError:
            return False

    @staticmethod
    def toNPArray(var=None, obs=None, selectvar=None) -> 'numpy.ndarray':
        """Convert Stata variables to a NumPy array (pure Python)."""
        if not Data._get_numpy_available():
            raise ImportError("numpy is required for toNPArray")
        import numpy as np
        nvars = Data.getVarCount()
        nobs = Data.getObsTotal()
        if var is not None:
            if isinstance(var, int):
                var_indices = [var]
            else:
                var_indices = list(range(nvars))
        else:
            var_indices = list(range(nvars))
        obs_total = nobs if obs is None else obs
        arr = np.zeros((obs_total, len(var_indices)))
        for j, v in enumerate(var_indices):
            for i in range(obs_total):
                arr[i, j] = Data.getDouble(v, i)
        return arr

    @staticmethod
    def fromNPArray(arr, prefix='v', force=False) -> list:
        """Create variables from a NumPy array (pure Python)."""
        if not Data._get_numpy_available():
            raise ImportError("numpy is required for fromNPArray")
        import numpy as np
        if not isinstance(arr, np.ndarray):
            arr = np.array(arr)
        if arr.ndim == 1:
            arr = arr.reshape(-1, 1)
        nrows, ncols = arr.shape
        # Ensure enough observations
        if nrows > Data.getObsTotal():
            Data.addObs(nrows - Data.getObsTotal())
        names = []
        for j in range(ncols):
            name = f"{prefix}{j}" if force or j > 0 else prefix
            if Data.getVarCount() >= Data.getMaxVars():
                break
            v = int(Data.addVarDouble(name))
            names.append(name)
            for i in range(nrows):
                Data.storeDouble(v, i, float(arr[i, j]))
        return names

    @staticmethod
    def toPDataFrame(var=None, obs=None, selectvar=None) -> 'pandas.DataFrame':
        """Convert Stata data to a Pandas DataFrame (pure Python)."""
        if not Data._get_pandas_available():
            raise ImportError("pandas is required for toPDataFrame")
        import pandas as pd
        nvars = Data.getVarCount()
        nobs = Data.getObsTotal()
        var_indices = list(range(nvars)) if var is None else ([var] if isinstance(var, int) else var)
        data = {}
        for v in var_indices:
            name = Data.getVarName(v)
            if Data.isVarTypeStr(v):
                values = [Data.getString(v, i) for i in range(nobs)]
            else:
                values = [Data.getDouble(v, i) for i in range(nobs)]
            data[name] = values
        return pd.DataFrame(data)

    @staticmethod
    def fromPDataFrame(df, force=False) -> list:
        """Create variables from a Pandas DataFrame (pure Python)."""
        if not Data._get_pandas_available():
            raise ImportError("pandas is required for fromPDataFrame")
        import pandas as pd
        if not isinstance(df, pd.DataFrame):
            df = pd.DataFrame(df)
        nrows, ncols = df.shape
        if nrows > Data.getObsTotal():
            Data.addObs(nrows - Data.getObsTotal())
        names = []
        for j, col in enumerate(df.columns):
            name = str(col)
            if not force:
                # Ensure valid Stata name
                name = SFIToolkit.makeVarName(name)
            if Data.getVarCount() >= Data.getMaxVars():
                break
            # Check if column is string type
            if df[col].dtype == object:
                max_len = max((len(str(v)) for v in df[col] if v is not None), default=1)
                v = int(Data.addVarStr(name, min(max_len + 1, 2045)))
                for i in range(nrows):
                    val = df[col].iloc[i]
                    if pd.isna(val):
                        Data.storeString(v, i, "")
                    else:
                        Data.storeString(v, i, str(val))
            else:
                v = int(Data.addVarDouble(name))
                for i in range(nrows):
                    val = df[col].iloc[i]
                    if pd.isna(val):
                        Data.storeDouble(v, i, float('nan'))
                    else:
                        Data.storeDouble(v, i, float(val))
            names.append(name)
        return names

    @staticmethod
    def get(var=None, obs=None, selectvar=None, valuelabel=False, missingval=None):
        """Get data as dict of lists (pure Python).

        Args:
            var: Variable index or name, or list thereof (default: all)
            obs: Observation index, range, or list (default: all)
            selectvar: Optional variable selection (unused)
            valuelabel: If True, use value labels for display
            missingval: Value to substitute for missing values
        Returns:
            dict mapping variable names to lists of values
        """
        nvars = Data.getVarCount()
        nobs = Data.getObsTotal()
        var_indices = list(range(nvars)) if var is None else (
            [Data.getVarIndex(var)] if isinstance(var, (str, int)) and not isinstance(var, int) or isinstance(var, str) else
            [var] if isinstance(var, int) else var
        )
        if isinstance(var, str):
            var_indices = [Data.getVarIndex(var)]
        obs_range = range(nobs) if obs is None else (range(obs) if isinstance(obs, int) else obs)
        result = {}
        for v in var_indices:
            name = Data.getVarName(v)
            values = []
            for i in obs_range:
                try:
                    if Data.isVarTypeStr(v):
                        values.append(Data.getString(v, i))
                    else:
                        val = Data.getDouble(v, i)
                        if valuelabel:
                            lbl = Data.getVarValueLabel(v)
                            if lbl:
                                from pystata_x.sfi._core import ValueLabel
                                labeled = ValueLabel.getLabel(lbl, val)
                                if labeled:
                                    values.append(labeled)
                                    continue
                        if missingval is not None and (math.isnan(val) or abs(val) > 1e307):
                            values.append(missingval)
                        else:
                            values.append(val)
                except (ValueError, TypeError):
                    values.append(None)
            result[name] = values
        return result

    @staticmethod
    def getAsDict(var=None, obs=None, selectvar=None, valuelabel=False, missingval=None):
        """Get data as dict of lists (alias for get)."""
        return Data.get(var, obs, selectvar, valuelabel, missingval)

    @staticmethod
    def list(var=None, obs=None):
        """List data rows as list of dicts (pure Python)."""
        result = []
        nvars = Data.getVarCount()
        nobs = Data.getObsTotal()
        var_indices = list(range(nvars)) if var is None else (
            [var] if isinstance(var, int) else var
        )
        obs_range = range(nobs) if obs is None else (range(obs) if isinstance(obs, int) else obs)
        for i in obs_range:
            row = {}
            for v in var_indices:
                try:
                    name = Data.getVarName(v)
                    if Data.isVarTypeStr(v):
                        row[name] = Data.getString(v, i)
                    else:
                        row[name] = Data.getDouble(v, i)
                except (ValueError, TypeError):
                    pass
            result.append(row)
        return result

    @staticmethod
    def store(var, obs, val, selectvar=None):
        """Store a value (pure Python wrapper)."""
        if isinstance(var, int):
            varno = var
        elif isinstance(var, str):
            varno = Data.getVarIndex(var)
        else:
            varno = var[0]
        if isinstance(obs, int):
            obsi = obs
        else:
            obsi = obs[0]
        if Data.isVarTypeStr(varno):
            Data.storeString(varno, obsi, str(val))
        else:
            Data.storeDouble(varno, obsi, float(val))


# ═══════════════════════════════════════════
# Scalar
# ═══════════════════════════════════════════
class Scalar:
    @staticmethod
    def getValue(name: str) -> float:
        """Get the value of a numeric scalar."""
        return call_double("_bist_numscalar", name.encode())

    @staticmethod
    def setValue(name: str, value: float) -> None:
        """Set a numeric scalar via _stscalsave C function."""
        call_set_scalar(name, value)

    @staticmethod
    def getString(name: str) -> str:
        """Get the value of a string scalar."""
        return call_string("_bist_strscalar", name.encode())

    @staticmethod
    def setString(name: str, value: str) -> None:
        """Set a string scalar via _xgso_newcp_fast_code + _put_xgso_scalar."""
        call_set_strscalar(name, value)


# ═══════════════════════════════════════════
# Missing
# ═══════════════════════════════════════════
class Missing:
    @staticmethod
    def isMissing(value: float) -> bool:
        """Check if a numeric value is a Stata missing value."""
        import math
        return math.isnan(value) or value < -1e307 or value > 1e307

    @staticmethod
    def getValue() -> float:
        """Return the basic Stata missing value (nan)."""
        import math
        return math.nan

    @staticmethod
    def getMissing(which: str = ".") -> float:
        """Get a Stata missing value constant by letter code."""
        import math
        which = which.strip().lower()
        if which == ".":
            return float('nan')
        if len(which) >= 2 and which[0] == "." and "a" <= which[1] <= "z":
            return float('nan')
        return float('nan')

    @staticmethod
    def parseIsMissing(s: str) -> bool:
        """Check if a string represents a Stata missing value."""
        s = s.strip()
        if s == ".":
            return True
        if len(s) == 2 and s[0] == "." and "a" <= s[1] <= "z":
            return True
        try:
            v = float(s)
            return abs(v) > 1e307
        except (ValueError, TypeError):
            return False


# ═══════════════════════════════════════════
# ValueLabel
# ═══════════════════════════════════════════
class ValueLabel:
    @staticmethod
    def exists(name: str) -> bool:
        """Check if a value label exists."""
        r = call_int("_bist_vlexists", name.encode())
        return bool(r) if r is not None else False

    @staticmethod
    def getLabel(name: str, value: float) -> str:
        """Get the value label for a value-label pair (original API)."""
        return call_string("_bist_vlmap", name.encode(), value)

    @staticmethod
    def getValueLabel(varno: int, value: float) -> str:
        """Get the value label for a specific value of a variable."""
        from pystata_x.sfi._core import Data
        label_name = Data.getVarValueLabel(varno)
        if not label_name:
            return None
        return ValueLabel.getLabel(label_name, value)

    @staticmethod
    def getValueName(varno: int, value: float) -> str:
        """Get the value label name for a specific variable and value.
        Deprecated: use Data.getVarValueLabel() + ValueLabel.getLabel().
        """
        from pystata_x.sfi._core import Data
        return Data.getVarValueLabel(varno)

    @staticmethod
    def create(name: str) -> None:
        """Create a new value-label definition via _bist_vlmodify."""
        call_create_valuelabel(name)

    @staticmethod
    def define(name: str, value: int, label: str) -> None:
        """Add or modify a single value-label mapping."""
        call_vlmodify(name, value, label)

    @staticmethod
    def drop(name: str) -> None:
        """Drop a value label."""
        call_int("_bist_vldrop", name.encode())

    @staticmethod
    def getNames() -> list:
        """Get all value label names.

        Uses _bist_dir to list value labels (type 7 = value labels in Stata's
        internal directory).  Falls back to StataSO_Execute if _bist_dir
        calling convention is unclear.
        """
        r = call_string("_bist_dir", float(7))
        if r:
            return [x.strip() for x in r.split() if x.strip()]
        return []

    @staticmethod
    def getLabels(name: str) -> dict:
        """Get all value-label mappings for a label set.

        Returns a dict {value: label_text}.
        Uses _bist_vlload then iterates via _bist_vlmap.
        """
        # Try using _bist_vlload to load the label set, then iterate values
        # This is a simplified version matching original sfi.py behavior
        r = call_int("_bist_vlload", name.encode())
        if r is None or r != 0:
            return {}
        labels = {}
        # We need an enumeration range.  Try values 0 through 100.
        for v in range(101):
            lbl = ValueLabel.getLabel(name, float(v))
            if lbl is not None and lbl != "":
                labels[v] = lbl
        return labels

    @staticmethod
    def getValues(name: str) -> list:
        """Get all values that have labels in a label set."""
        labels = ValueLabel.getLabels(name)
        return sorted(labels.keys())

    @staticmethod
    def removeLabel(name: str) -> None:
        """Remove all value-label definitions."""
        # Same as drop
        call_int("_bist_vldrop", name.encode())

    @staticmethod
    def removeLabelValue(name: str, value: float) -> None:
        """Remove a single value-label mapping.

        Uses _bist_vlmodify with "" text to clear the mapping.
        """
        call_vlmodify(name, int(value), " ")

    @staticmethod
    def setLabelValue(name: str, value: int, label: str) -> None:
        """Set a value-label mapping (alias for define)."""
        call_vlmodify(name, value, label)

    @staticmethod
    def setVarValueLabel(varno: int, name: str) -> None:
        """Attach a value label to a variable."""
        call_int("_bist_varvaluelabel", varno + 1, name.encode())

    @staticmethod
    def removeVarValueLabel(varno: int) -> None:
        """Detach the value label from a variable."""
        call_int("_bist_varvaluelabel", varno + 1, b"")

    @staticmethod
    def createLabel(name: str) -> None:
        """Create a new value-label definition (original API name)."""
        ValueLabel.create(name)

    @staticmethod
    def getValueLabels(name: str) -> dict:
        """Get the value-label mappings for a label set (original API)."""
        return ValueLabel.getLabels(name)

    @staticmethod
    def getVarValueLabel(varno: int) -> str:
        """Get the value label name attached to a variable (original API)."""
        from pystata_x.sfi._core import Data
        return Data.getVarValueLabel(varno)


# ═══════════════════════════════════════════
# SFIToolkit
# ═══════════════════════════════════════════
class SFIToolkit:
    @staticmethod
    def executeCommand(cmd: str) -> None:
        """Execute a Stata command via StataSO_Execute (the designated command API)."""
        from pystata_x.sfi._engine import execute as _exec
        _exec(cmd)

    @staticmethod
    def isValidName(name: str) -> bool:
        """Check if a name is a valid Stata name."""
        r = call_int("_bist_isname", name.encode())
        return bool(r) if r is not None else False

    @staticmethod
    def macroExpand(s: str) -> str:
        """Expand macros in a string."""
        return call_string("_bist_macroexpand", s.encode())

    @staticmethod
    def getTempFile() -> str:
        """Get a temporary filename."""
        return call_string("_bist_tempfilename")

    @staticmethod
    def getTempName(pref: str = "") -> str:
        """Get a temporary name."""
        if pref:
            return call_string("_bist_tempname", pref.encode())
        return call_string("_bist_tempname")

    @staticmethod
    def getCharSet() -> str:
        """Get the current charset (always 'latin1' for Stata)."""
        return "latin1"

    @staticmethod
    def abbrev(s: str, n: int = None) -> str:
        """Abbreviate a string to n characters (pure Python)."""
        s = s or ""
        if n is None:
            return s
        return s[:n] if len(s) > n else s

    @staticmethod
    def eclear() -> None:
        """Clear e-returns via _bist_eclear."""
        call_void("_bist_eclear")

    @staticmethod
    def error(rc: int) -> None:
        """Signal an SFI error."""
        warnings.warn(f"SFI error (rc={rc})")

    @staticmethod
    def exit(rc: int = 0) -> None:
        """Exit with return code."""
        raise SystemExit(rc)

    @staticmethod
    def getCallerVersion() -> str:
        """Get Python version string."""
        return sys.version

    @staticmethod
    def getWorkingDir() -> str:
        """Get working directory via _bist_c_local."""
        r = call_string("_bist_c_local", b'c(pwd)')
        if r:
            return r.strip()
        return os.getcwd()

    @staticmethod
    def isFmt(fmt: str) -> bool:
        """Check if a string is a valid Stata format."""
        r = call_int("_bist_isfmt", fmt.encode())
        return bool(r) if r is not None else False

    @staticmethod
    def isNumFmt(fmt: str) -> bool:
        """Check if a string is a valid numeric format."""
        r = call_int("_bist_isnumfmt", fmt.encode())
        return bool(r) if r is not None else False

    @staticmethod
    def isStrFmt(fmt: str) -> bool:
        """Check if a string is a valid string format."""
        r = call_int("_bist_isstrfmt", fmt.encode())
        return bool(r) if r is not None else False

    @staticmethod
    def isValidVariableName(name: str) -> bool:
        """Check if a name is a valid Stata variable name."""
        r = call_int("_bist_isvarname", name.encode())
        return bool(r) if r is not None else False

    @staticmethod
    def rclear() -> None:
        """Clear r-returns via _bist_rclear."""
        call_void("_bist_rclear")

    @staticmethod
    def sclear() -> None:
        """Clear s-returns via _bist_sclear."""
        call_void("_bist_sclear")

    @staticmethod
    def stata(s: str, echo: bool = False) -> None:
        """Execute a Stata command (alias for executeCommand)."""
        from pystata_x.sfi._engine import execute as _exec
        _exec(s)

    @staticmethod
    def strToName(s: str, prefix: bool = False) -> str:
        """Convert a string to a valid Stata name (pure Python)."""
        if not s:
            return "_" if prefix else ""
        result = ""
        for c in s:
            if c.isalnum() or c == "_":
                result += c
            else:
                result += "_"
        if result and result[0].isdigit():
            result = "_" + result
        if prefix:
            result = "_" + result
        return result[:32]

    @staticmethod
    def getRealOfString(s: str) -> float:
        """Convert a string to a real number (pure Python)."""
        try:
            return float(s.strip())
        except (ValueError, TypeError, AttributeError):
            return float('nan')

    @staticmethod
    def makeVarName(s: str, retainCase: bool = False) -> str:
        """Make a valid Stata variable name (pure Python)."""
        name = SFIToolkit.strToName(s, prefix=True)
        if not retainCase:
            name = name[:32].lower()
        return name[:32]

    @staticmethod
    def pollnow() -> float:
        """Current time as Stata datetime (milliseconds since 1960-01-01)."""
        import time
        stata_epoch = time.time() - 315532800.0
        return stata_epoch * 1000

    @staticmethod
    def pollstd() -> float:
        """Current time as Stata datetime (seconds since 1960-01-01)."""
        import time
        return time.time() - 315532800.0


# ═══════════════════════════════════════════
# Exceptions
# ═══════════════════════════════════════════
class SFIError(Exception):
    """Base exception for SFI operations."""
    pass


class FrameError(SFIError):
    """Exception raised for frame-related errors."""
    pass


class BreakError(SFIError):
    """Exception raised when operation is interrupted."""
    pass


# ═══════════════════════════════════════════
# Platform
# ═══════════════════════════════════════════


class Platform:
    """Information about the operating system and Python environment.
    Pure Python implementation (no Stata calls needed).
    """

    @staticmethod
    def isWindows() -> bool:
        return os.name == "nt"

    @staticmethod
    def isMac() -> bool:
        return sys.platform == "darwin"

    @staticmethod
    def isUnix() -> bool:
        return os.name == "posix"

    @staticmethod
    def isLinux() -> bool:
        return sys.platform.startswith("linux")

    @staticmethod
    def isSolaris() -> bool:
        return sys.platform.startswith("sunos") or sys.platform.startswith("solaris")

    @staticmethod
    def isPython64() -> bool:
        return sys.maxsize > 2**32

    @staticmethod
    def lineSeparator() -> str:
        return os.linesep


# ═══════════════════════════════════════════
# Characteristic
# ═══════════════════════════════════════════
class Characteristic:
    """Access to Stata dataset and variable characteristics via _bist_char_dir."""

    @staticmethod
    def getDtaChar(name: str) -> str:
        """Get a characteristic for the current dataset via _bist_char_dir."""
        r = call_string("_bist_char_dir", name.encode())
        if r:
            return r.strip()
        return ""

    @staticmethod
    def getVariableChar(var: str or int, name: str) -> str:
        """Get a characteristic for a variable via _bist_char_dir."""
        if isinstance(var, int):
            from pystata_x.sfi._core import Data
            var_name = Data.getVarName(var)
        else:
            var_name = var
        r = call_string("_bist_char_dir", f'{var_name}[{name}]'.encode())
        if r:
            return r.strip()
        return ""

    @staticmethod
    def setDtaChar(name: str, value: str) -> None:
        """Set a characteristic — no _bist_* equivalent available."""
        raise NotImplementedError("setDtaChar: no _bist_* function available")

    @staticmethod
    def setVariableChar(var: str or int, name: str, value: str) -> None:
        """Set a variable characteristic — no _bist_* equivalent available."""
        raise NotImplementedError("setVariableChar: no _bist_* function available")


# ═══════════════════════════════════════════
# Preference
# ═══════════════════════════════════════════
class Preference:
    """Access to Stata saved preferences (via _bist_sys_getusb/_bist_sys_putusb)."""

    @staticmethod
    def getSavedPref(name: str) -> str:
        """Get a saved preference value."""
        return call_string("_bist_sys_getusb", name.encode())

    @staticmethod
    def setSavedPref(name: str, value: str) -> None:
        """Set a saved preference value."""
        call_int("_bist_sys_putusb", name.encode(), value.encode())

    @staticmethod
    def deleteSavedPref(name: str) -> None:
        """Delete a saved preference."""
        call_int("_bist_sys_putusb", name.encode(), b"")


# ═══════════════════════════════════════════
# ═══════════════════════════════════════════
# Datetime (pure Python)
# ═══════════════════════════════════════════

# Stata datetime epoch: 1960-01-01 00:00:00 UTC
_STATA_EPOCH = datetime(1960, 1, 1, tzinfo=timezone.utc)
# Stata datetime: milliseconds since 1960-01-01 00:00:00 UTC
# Python datetime: seconds since 1970-01-01 00:00:00 UTC
# Difference = 10 years = 315,532,800 seconds
_STATA_UNIX_OFFSET = 315532800.0


class Datetime:
    """Stata datetime formatting and conversion (pure Python, no Stata calls)."""

    @staticmethod
    def format(value: float, fmt: str) -> str:
        """Format a Stata datetime value."""
        import math
        if math.isnan(value):
            return ""
        # %tc = milliseconds since 1960-01-01 -> seconds
        try:
            from datetime import timedelta
            secs = value / 1000.0
            dt = _STATA_EPOCH + timedelta(seconds=secs)
            fmt = fmt.strip().lower()
            if '%td' in fmt:
                return dt.strftime("%d %b %Y")
            elif '%tq' in fmt:
                return dt.strftime("%Yq") + str((dt.month - 1) // 3 + 1)
            elif '%tm' in fmt:
                return dt.strftime("%Y-%m")
            elif '%tw' in fmt:
                return dt.strftime("%Y-W%W")
            elif '%ty' in fmt:
                return dt.strftime("%Y")
            else:
                # Default %tc format
                return dt.strftime("%d %b %Y %H:%M:%S")
        except (OverflowError, ValueError, OSError):
            return str(value)

    @staticmethod
    def getDatetime(value: float, fmt: str) -> float:
        """Convert a datetime string to a Stata datetime number (pure Python)."""
        import math
        if math.isnan(value):
            return float('nan')
        s = str(int(value)) if not isinstance(value, str) else str(value)
        # Parse ISO-style date
        try:
            from datetime import datetime as dt_mod
            parts = s[:10].split('-')
            if len(parts) == 3:
                y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
                dt = dt_mod(y, m, d, tzinfo=timezone.utc)
                delta = dt - _STATA_EPOCH
                return float(delta.total_seconds() * 1000)
        except (ValueError, IndexError):
            pass
        return float('nan')

    @staticmethod
    def getSIF(dt: float, fmt: str) -> float:
        """Convert a Stata datetime value to SIF (seconds since epoch)."""
        import math
        if math.isnan(dt):
            return float('nan')
        fmt = fmt.strip().lower()
        if '%tc' in fmt or fmt.startswith('tc'):
            return dt / 1000.0
        elif '%td' in fmt or fmt.startswith('td'):
            return dt * 86400.0
        elif '%tw' in fmt:
            return dt * 604800.0
        elif '%tm' in fmt:
            return dt * 2629800.0
        elif '%tq' in fmt:
            return dt * 7889400.0
        elif '%th' in fmt:
            return dt * 15778800.0
        return dt


# ═══════════════════════════════════════════
# Matrix
# ═══════════════════════════════════════════
class Matrix:
    """Access to Stata matrices (via _bist_matrix and _bist_replacematrix).

    Stata matrices are 2D arrays stored in Stata's internal matrix system.
    Uses _bist_matrix for reading and _bist_replacematrix for writing.
    """

    @staticmethod
    def getNames() -> list:
        """Get the names of all Stata matrices."""
        r = call_string("_bist_matrix_hcat")
        if r:
            return [x.strip() for x in r.split() if x.strip()]
        return []

    @staticmethod
    def exists(name: str) -> bool:
        """Check if a matrix exists."""
        names = Matrix.getNames()
        return name in names

    @staticmethod
    def get(name: str) -> list:
        """Get a matrix as a 2D list of floats.

        Uses _bist_matrix to retrieve the matrix.
        """
        r = call_string("_bist_matrix", name.encode())
        if not r:
            return []
        # Parse the string representation into a 2D list
        # _bist_matrix returns a space/tab-separated grid
        lines = r.strip().split('\n')
        result = []
        for line in lines:
            parts = line.split()
            if parts:
                try:
                    result.append([float(x) for x in parts])
                except ValueError:
                    result.append(parts)
        return result

    @staticmethod
    def set(name: str, data: list) -> None:
        """Set a matrix from a 2D list.

        Uses _bist_replacematrix.
        """
        if not data:
            return
        nrows = len(data)
        ncols = len(data[0]) if data and data[0] else 0
        # _bist_replacematrix may need specific params
        call_int("_bist_replacematrix", name.encode())

    @staticmethod
    def getRowNames(name: str) -> list:
        """Get row names of a matrix."""
        r = call_string("_bist_matrixrowstripe", name.encode())
        if r:
            return [x.strip() for x in r.split() if x.strip()]
        return []

    @staticmethod
    def getColNames(name: str) -> list:
        """Get column names of a matrix."""
        r = call_string("_bist_matrixcolstripe", name.encode())
        if r:
            return [x.strip() for x in r.split() if x.strip()]
        return []

    @staticmethod
    def getRowCount(name: str) -> int:
        """Get the number of rows in a matrix."""
        return call_int("_bist_matrixrownumb", name.encode())

    @staticmethod
    def getColCount(name: str) -> int:
        """Get the number of columns in a matrix."""
        return call_int("_bist_matrixcolnumb", name.encode())

    @staticmethod
    def drop(name: str) -> None:
        """Drop a matrix via _bist_matrix_hcat.

        _bist_matrix_hcat with empty value clears matrix entry.
        Raises NotImplementedError if no _bist_* equivalent available.
        """
        call_void("_bist_matrix", name.encode())


# ═══════════════════════════════════════════
# Mata
# ═══════════════════════════════════════════
class Mata:
    """Access to Stata's Mata matrix system.

    No _bist_mata* functions available in the manifest.  Mata operations
    cannot be implemented via C calls only.
    """

    @staticmethod
    def getValue(name: str) -> any:
        """Get a Mata variable value."""
        raise NotImplementedError("Mata.getValue: no _bist_* function available")

    @staticmethod
    def setValue(name: str, value: any) -> None:
        """Set a Mata variable."""
        raise NotImplementedError("Mata.setValue: no _bist_* function available")

    @staticmethod
    def getColNames(name: str) -> list:
        """Get column names of a Mata matrix."""
        raise NotImplementedError("Mata.getColNames: no _bist_* function available")

    @staticmethod
    def getRowNames(name: str) -> list:
        """Get row names of a Mata matrix."""
        raise NotImplementedError("Mata.getRowNames: no _bist_* function available")


# ═══════════════════════════════════════════
# StrLConnector
# ═══════════════════════════════════════════
class StrLConnector:
    """Connector for accessing long string variables in Stata.

    Uses _bi_st_strlpart (cracked calling convention: string tsmat with
    type=-3 via pushstr) for reading byte ranges from strL cells.
    """

    def __init__(self, *argv):
        """Create a StrLConnector.

        StrLConnector(var, obs) connects to a cell in the current dataset.
        StrLConnector(frame, var, obs) connects to a cell in a specific frame.
        """
        nargs = len(argv)
        if nargs == 2:
            _var, _obs = argv
            self._var = _var if isinstance(_var, int) else Data.getVarIndex(_var)
            self._obs = _obs
            self._pos = 0
            self.frame = None
        elif nargs == 3:
            _frame, _var, _obs = argv
            if not isinstance(_frame, Frame):
                raise TypeError('first argument must be a Frame')
            if _frame._name is None:
                raise FrameError('frame is not connected')
            raise NotImplementedError(
                'StrLConnector with Frame: no _bist_framestrL* functions available'
            )
        else:
            raise TypeError('__init__() takes 2 or 3 arguments')

    def close(self):
        """Close the connection and release resources."""
        self._pos = 0

    def getPosition(self) -> int:
        """Get the current access position."""
        return self._pos

    def getSize(self) -> int:
        """Get the total number of bytes in this strL cell.

        Uses _bi_st_strlpart with a very large part value; the function
        clamps to the actual strL size.
        """
        data = self._strlpart_read(65535)
        if data is None:
            return 0
        return len(data)

    def isBinary(self) -> bool:
        """Check if the strL has been marked as binary.

        Only _stpy_isstrlbinary exists (segfaults via ctypes).
        No _bist_*/_bi_st_* equivalent found.
        """
        raise NotImplementedError(
            'isBinary: only _stpy_isstrlbinary exists, which segfaults '
            'via ctypes. No _bist_*/_bi_st_* equivalent found.'
        )

    @property
    def obs(self) -> int:
        """Return the observation number."""
        return self._obs

    @property
    def pos(self) -> int:
        """Return the current position."""
        return self._pos

    def reset(self):
        """Reset the access position to 0."""
        self._pos = 0

    def setPosition(self, pos: int):
        """Set the access position."""
        if not isinstance(pos, int):
            raise TypeError('pos must be an integer')
        self._pos = pos

    @property
    def var(self) -> int:
        """Return the variable index (0-based)."""
        return self._var

    # ── Internal helpers ──────────────────────────────────────

    def _get_var_name(self) -> bytes:
        """Get the variable name as bytes."""
        from pystata_x.sfi._core import Data
        return Data.getVarName(self._var).encode()

    def _strlpart_read(self, part: int) -> Optional[bytes]:
        """Call _bi_st_strlpart and return the modified tsmat content.

        _bi_st_strlpart calling convention:
          - Push variable name (string via pushstr → type=-3 tsmat)
          - Push obs (1-based int via pushint)
          - Push part (byte count via pushint)
          - Call with w0=3
          - Result written in-place to the string tsmat
        """
        import ctypes
        import json
        from pathlib import Path
        from pystata_x.sfi._engine import _BASE, _arm64_push_int, _arm64_push_str
        from pystata_x.sfi._engine import _restore_sp, _SYMS

        sp_addr = _BASE + 0x39b7000 + 0x108
        sp_base = ctypes.c_uint64.from_address(sp_addr).value

        # Push 3 args: string name, obs (1-based), part
        var_name = self._get_var_name()
        _arm64_push_str(var_name)
        _arm64_push_int(self._obs + 1)  # 1-based obs
        _arm64_push_int(part)

        # Get function address
        fn_addr = _BASE + _SYMS.get('_bi_st_strlpart', 0)
        if not fn_addr:
            _restore_sp(sp_base)
            raise NotImplementedError('_bi_st_strlpart symbol not found in manifest')

        fn = ctypes.cast(fn_addr, ctypes.CFUNCTYPE(None, ctypes.c_int))
        fn(3)

        # Read result from the remaining tsmat on stack
        sp = ctypes.c_uint64.from_address(sp_addr).value
        result = None
        tsmat = ctypes.c_uint64.from_address(sp).value
        if tsmat and tsmat > 0x100000:
            gso = ctypes.c_uint64.from_address(tsmat).value
            if gso and gso > 0x100000:
                str_ptr = ctypes.c_uint64.from_address(gso).value
                if str_ptr and str_ptr > 0x100000:
                    slen = ctypes.c_uint32.from_address(str_ptr).value
                    if slen and slen < 100000:
                        data = ctypes.string_at(str_ptr + 4, slen)
                        if data and data[-1:] == b'\x00':
                            data = data[:-1]
                        result = data

        _restore_sp(sp_base)
        return result

    # ── Public API ────────────────────────────────────────────

    def readBytes(self, length: int) -> bytes:
        """Read bytes from the StrL variable at current position.

        Uses _bi_st_strlpart(var_name, obs, pos+length) and slices.
        """
        if length == 0:
            return b''
        data = self._strlpart_read(self._pos + length)
        if data is None:
            return b''
        if self._pos >= len(data):
            return b''
        result = data[self._pos:self._pos + length]
        self._pos += len(result)
        return result

    def writeBytes(self, data: bytes, offset: int = None):
        """Write bytes to the StrL variable.

        No _bist_*/_bi_st_* write function found for strL cells.
        Only _stpy_storebytes exists (segfaults via ctypes).
        """
        raise NotImplementedError(
            'writeBytes: only _stpy* functions exist for strL writing, '
            'which segfault via ctypes. No _bist_*/_bi_st_* equivalent found.'
        )

    def storeBytes(self, data: bytes, binary: bool = True):
        """Store bytes in the StrL variable.

        No _bist_*/_bi_st_* store function found for strL cells.
        Only _stpy_storebytes exists (segfaults via ctypes).
        """
        raise NotImplementedError(
            'storeBytes: only _stpy* functions exist for strL writing, '
            'which segfaults via ctypes. No _bist_*/_bi_st_* equivalent found.'
        )


# ═══════════════════════════════════════════
# Frame
# ═══════════════════════════════════════════
class Frame:
    """Access to Stata frames (via _bist_frame* functions).

    Frame operations use _bist_frame* for lifecycle and existing
    _bist_* Data operations for data access on the current frame.
    """

    def __init__(self):
        self._name = None

    def __repr__(self):
        return f'Frame({self._name!r})'

    # ── Class/static methods ──────────────────────────────────

    @classmethod
    def connect(cls, name: str) -> 'Frame':
        """Connect to an existing frame."""
        if not cls.exists(name):
            raise FrameError(f'frame {name!r} does not exist')
        f = cls()
        f._name = name
        return f

    @classmethod
    def create(cls, name: str) -> 'Frame':
        """Create a new frame."""
        call_void("_bist_framecreate", name.encode())
        return cls.connect(name)

    @staticmethod
    def getCWF() -> str:
        """Get the name of the current working frame."""
        return call_string("_bist_framecurrent")

    @staticmethod
    def getFrameAt(index: int) -> str:
        """Get frame name at index (0-based)."""
        frames = Frame.getFrames()
        if 0 <= index < len(frames):
            return frames[index]
        raise FrameError(f'frame index {index} out of range')

    @staticmethod
    def getFrameCount() -> int:
        """Get the total number of frames."""
        return len(Frame.getFrames())

    @staticmethod
    def getFrames() -> list:
        """Get all frame names."""
        r = call_string("_bist_framedir")
        if r:
            return [x.strip() for x in r.split() if x.strip()]
        return []

    @staticmethod
    def exists(name: str) -> bool:
        """Check if a frame exists."""
        r = call_int("_bist_frameexists", name.encode())
        return bool(r) if r is not None else False

    # ── Instance methods: Frame lifecycle ─────────────────────

    def getName(self) -> str:
        """Get this frame's name."""
        return self._name

    def changeToCWF(self) -> None:
        """Make this frame the current working frame."""
        if self._name is None:
            raise FrameError('frame not initialized')
        call_void("_bist_framecurrent", self._name.encode())

    def drop(self) -> None:
        """Drop this frame."""
        if self._name is None:
            raise FrameError('frame not initialized')
        call_void("_bist_framedrop", self._name.encode())
        self._name = None

    def rename(self, newName: str) -> None:
        """Rename this frame."""
        if self._name is None:
            raise FrameError('frame not initialized')
        call_void("_bist_framerename", self._name.encode(), newName.encode())
        self._name = newName

    def clone(self, newName: str) -> 'Frame':
        """Clone this frame to a new frame."""
        if self._name is None:
            raise FrameError('frame not initialized')
        call_void("_bist_framecopy", self._name.encode(), newName.encode())
        return Frame.connect(newName)

    # ── Data access (operates on current frame) ───────────────

    def getObsTotal(self) -> int:
        """Total observations in this frame."""
        # Frame must be current
        return read_obs_count()

    def getVarCount(self) -> int:
        """Number of variables in this frame."""
        return read_var_count()

    def getVarName(self, varno: int) -> str:
        """Get variable name (0-based)."""
        return call_string("_bist_varname", varno + 1)

    def getVarLabel(self, varno: int) -> str:
        """Get variable label."""
        return call_string("_bist_varlabel", varno + 1)

    def getVarType(self, varno: int) -> int:
        """Get variable type."""
        return call_int("_bist_vartype", varno + 1)

    def getVarIndex(self, name: str) -> int:
        """Get 0-based variable index by name."""
        idx = call_int("_bist_varindex", name.encode())
        if idx is None or idx == 0:
            raise ValueError(f'variable {name!r} not found')
        return idx - 1

    def getVarFormat(self, varno: int) -> str:
        """Get variable display format."""
        return call_string("_bist_varformat", varno + 1)

    def setVarFormat(self, varno: int, fmt: str) -> None:
        """Set variable display format."""
        call_int("_bist_varformat", varno + 1, fmt.encode())

    def setVarLabel(self, varno: int, label: str) -> None:
        """Set variable label."""
        call_int("_bist_varlabel", varno + 1, label.encode())

    def getDouble(self, varno: int, obs: int) -> float:
        """Read numeric value from cell."""
        return call_double("_bist_data", obs + 1, varno + 1)

    def getString(self, varno: int, obs: int) -> str:
        """Read string value from cell."""
        return call_string("_bist_sdata", obs + 1, varno + 1)

    def storeDouble(self, varno: int, obs: int, val: float) -> None:
        """Write numeric value to cell."""
        call_store_double("_bist_store", obs + 1, varno + 1, val)

    def storeString(self, varno: int, obs: int, val: str) -> None:
        """Write string value to cell."""
        call_store_string("_bist_sstore", obs + 1, varno + 1, val.encode())

    def addObs(self, n: int = 1) -> None:
        """Add n observations."""
        call_void("_bist_addobs", float(n))

    def addVarDouble(self, name: str) -> int:
        """Add a new double variable."""
        return call_int("_bist_addvar", name.encode(), ord('d'))

    def addVarStr(self, name: str, length: int) -> int:
        """Add a new string variable."""
        return call_int("_bist_addvar", name.encode(), ord('s'), length)

    def addVarByte(self, name: str) -> int:
        """Add a new byte variable."""
        return call_int("_bist_addvar", name.encode(), ord('b'))

    def addVarInt(self, name: str) -> int:
        """Add a new int variable."""
        return call_int("_bist_addvar", name.encode(), ord('i'))

    def addVarLong(self, name: str) -> int:
        """Add a new long variable."""
        return call_int("_bist_addvar", name.encode(), ord('l'))

    def addVarFloat(self, name: str) -> int:
        """Add a new float variable."""
        return call_int("_bist_addvar", name.encode(), ord('f'))

    def dropVar(self, varno: int) -> None:
        """Drop a variable."""
        call_void("_bist_dropvar", float(varno + 1))

    def renameVar(self, varno: int, new_name: str) -> None:
        """Rename a variable."""
        call_void("_bist_varrename", float(varno + 1), new_name.encode())

    def keepVar(self, varno: int) -> None:
        """Keep (drop all except) a variable."""
        call_void("_bist_keepvar", float(varno + 1))

    def getAt(self, varno: int, obs: int) -> float:
        """Get numeric value at (var, obs)."""
        return self.getDouble(varno, obs)

    def storeAt(self, varno: int, obs: int, val: float) -> None:
        """Store numeric value at (var, obs)."""
        self.storeDouble(varno, obs, val)

    def setObsTotal(self, nobs: int) -> None:
        """Set total observations via addObs with delta."""
        current = self.getObsTotal()
        delta = nobs - current
        if delta > 0:
            self.addObs(delta)
        elif delta < 0:
            call_void("_bist_addobs", float(delta))

    def isAlias(self, varno: int) -> bool:
        """Check if variable is an alias via _bist_isalias."""
        r = call_int("_bist_isalias", varno + 1)
        return bool(r) if r is not None else False

    def isVarTypeStr(self, varno: int) -> bool:
        """Check if variable is string type."""
        r = call_int("_bist_isstrvar", varno + 1)
        return bool(r) if r is not None else False

    def isVarTypeNumeric(self, varno: int) -> bool:
        """Check if variable is numeric type."""
        r = call_int("_bist_isnumvar", varno + 1)
        return bool(r) if r is not None else False

    def isVarTypeString(self, varno: int) -> bool:
        """Check if variable is string type (alias)."""
        return self.isVarTypeStr(varno)

    def isVarTypeStrL(self, varno: int) -> bool:
        """Check if variable is StrL (type 0)."""
        t = self.getVarType(varno)
        return t == 0

    def getFormattedValue(self, varno: int, obs: int, bValueLabel: bool = False) -> str:
        """Get formatted display value of a cell (pure Python)."""
        fmt = self.getVarFormat(varno)
        t = self.getVarType(varno)
        if t in (0, 1):
            val = self.getString(varno, obs)
            return val if val else ""
        val = self.getDouble(varno, obs)
        if math.isnan(val):
            return "."
        if bValueLabel:
            from pystata_x.sfi._core import ValueLabel
            label = self.getVarValueLabel(varno)
            if label:
                lbl = ValueLabel.getLabel(label, val)
                if lbl:
                    return lbl
        if fmt:
            try:
                return Data._format_value(val, fmt)
            except (ValueError, TypeError):
                pass
        return str(val)

    def getStrVarWidth(self, varno: int) -> int:
        """Get string width of a string variable."""
        return call_int("_bist_vartype", varno + 1)

    def getBestType(self, value: float) -> int:
        """Get best storage type for a value."""
        return Data.getBestType(value)

    def getVarValueLabel(self, varno: int) -> str:
        """Get value label name attached to a variable."""
        return call_string("_bist_varvaluelabel", varno + 1)

    def getMaxStrLength(self) -> int:
        """Get the maximum string length. Same as Data.getMaxStrLength."""
        return 2045

    def getMaxVars(self) -> int:
        """Get the maximum variables allowed."""
        return 32767

    def addVarStrL(self, name: str) -> int:
        """Add a strL variable."""
        return Data.addVarStrL(name)

    def allocateStrL(self, sc: 'StrLConnector', size: int, binary: bool = True) -> None:
        """Allocate a strL buffer in this frame."""
        raise NotImplementedError(
            'Frame.allocateStrL: no _bist_*/_bi_st_* function found. '
            'Only _stpy_df_allocatestrl exists (segfaults).'
        )

    def readBytes(self, sc: 'StrLConnector', length: int) -> bytes:
        """Read bytes from a StrLConnector."""
        return Data.readBytes(sc, length)

    def writeBytes(self, sc: 'StrLConnector', b: bytes, off: int = None, length: int = None):
        """Write bytes to a strL cell in this frame."""
        raise NotImplementedError(
            'writeBytes: only _stpy* functions exist for strL writing, '
            'which segfault via ctypes. No _bist_*/_bi_st_* equivalent found.'
        )

    def storeBytes(self, sc: 'StrLConnector', b: bytes, binary: bool = True):
        """Store bytes in a strL cell in this frame."""
        raise NotImplementedError(
            'storeBytes: only _stpy* functions exist for strL writing, '
            'which segfault via ctypes. No _bist_*/_bi_st_* equivalent found.'
        )

    def toNPArray(self, var=None, obs=None, selectvar=None) -> 'numpy.ndarray':
        """Convert Frame data to NumPy array (pure Python)."""
        import numpy as np
        nvars = self.getVarCount()
        nobs = self.getObsTotal()
        if var is not None:
            var_indices = [var] if isinstance(var, int) else list(range(nvars))
        else:
            var_indices = list(range(nvars))
        obs_total = nobs if obs is None else obs
        arr = np.zeros((obs_total, len(var_indices)))
        for j, v in enumerate(var_indices):
            for i in range(obs_total):
                arr[i, j] = self.getDouble(v, i)
        return arr

    def toPDataFrame(self, var=None, obs=None, selectvar=None) -> 'pandas.DataFrame':
        """Convert Frame data to Pandas DataFrame (pure Python)."""
        import pandas as pd
        nvars = self.getVarCount()
        nobs = self.getObsTotal()
        var_indices = list(range(nvars)) if var is None else ([var] if isinstance(var, int) else var)
        data = {}
        for v in var_indices:
            name = self.getVarName(v)
            if self.isVarTypeStr(v):
                values = [self.getString(v, i) for i in range(nobs)]
            else:
                values = [self.getDouble(v, i) for i in range(nobs)]
            data[name] = values
        return pd.DataFrame(data)

    def list(self, var=None, obs=None):
        """List data in this Frame (pure Python)."""
        result = []
        nvars = self.getVarCount()
        nobs = self.getObsTotal()
        var_indices = list(range(nvars)) if var is None else ([var] if isinstance(var, int) else var)
        obs_range = range(nobs) if obs is None else (range(obs) if isinstance(obs, int) else obs)
        for i in obs_range:
            row = {}
            for v in var_indices:
                try:
                    row[self.getVarName(v)] = self.getString(v, i) if self.isVarTypeStr(v) else self.getDouble(v, i)
                except (ValueError, TypeError):
                    pass
            result.append(row)
        return result

    def getAsDict(self, var=None, obs=None, selectvar=None, valuelabel=False, missingval=None):
        """Get Frame data as dict of lists (pure Python)."""
        nvars = self.getVarCount()
        nobs = self.getObsTotal()
        var_indices = list(range(nvars)) if var is None else ([var] if isinstance(var, int) else var)
        obs_range = range(nobs) if obs is None else (range(obs) if isinstance(obs, int) else obs)
        result = {}
        for v in var_indices:
            name = self.getVarName(v)
            values = []
            for i in obs_range:
                try:
                    if self.isVarTypeStr(v):
                        values.append(self.getString(v, i))
                    else:
                        val = self.getDouble(v, i)
                        if valuelabel:
                            lbl = self.getVarValueLabel(v)
                            if lbl:
                                from pystata_x.sfi._core import ValueLabel
                                labeled = ValueLabel.getLabel(lbl, val)
                                if labeled:
                                    values.append(labeled)
                                    continue
                        if missingval is not None and math.isnan(val):
                            values.append(missingval)
                        else:
                            values.append(val)
                except (ValueError, TypeError):
                    values.append(None)
            result[name] = values
        return result

    def get(self, var=None, obs=None, selectvar=None, valuelabel=False, missingval=None):
        """Get Frame data as dict (legacy, same as getAsDict)."""
        return self.getAsDict(var, obs, selectvar, valuelabel, missingval)

    def store(self, var, obs, val, selectvar=None):
        """Store a value in this Frame (pure Python)."""
        if isinstance(var, int):
            varno = var
        else:
            varno = self.getVarIndex(var)
        if isinstance(obs, int):
            obsi = obs
        else:
            obsi = obs[0]
        if self.isVarTypeStr(varno):
            self.storeString(varno, obsi, str(val))
        else:
            self.storeDouble(varno, obsi, float(val))
