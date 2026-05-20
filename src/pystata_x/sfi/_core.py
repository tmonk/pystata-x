"""SFI API implementation — multi-tier: C calls + executeCommand + manifest.

Architecture
------------
SFI methods are implemented via three tiers depending on availability:

**Tier 1 — Direct _bist_*/_bi_st_* C calls** (fastest, preferred for data):
  - Cell data: _bist_data, _bist_sdata, _bist_store, _bist_sstore
  - Variable metadata: _bist_varname, _bist_varlabel, _bist_varformat, etc.
  - Macros: _bist_global, _bist_putglobal
  - Scalars: _bist_numscalar, _bist_strscalar (read); _stscalsave,
    _xgso_newcp_fast_code + _put_xgso_scalar (write, via manifest lookup)
  - Value labels: _bist_vlexists, _bist_vlmap, _bist_vlsearch, _bist_vldrop
  - StrL reads: _bi_st_strlpart (type=-3 tsmat convention)
  - Obs/var counts: _bist_nobs / _bist_nvar (via manifest lookup, not hardcoded)

**Tier 2 — executeCommand** (StataSO_Execute, for operations without C API):
  - Matrix: ALL 17 reference API methods (_bist_matrix* work on estimation
    results bytecode, not user matrices)
  - Mata: ALL 17 reference API methods (no _bist_mata* functions exist)
  - Characteristic.setDtaChar / setVariableChar (char define command)
  - Data.addVarStrL (generate strL command)
  - SFIToolkit.display/displayln/errprint/errprintln/formatValue/listReturn

**Tier 3 — Pure Python** (no Stata calls needed):
  - Platform, Datetime, SFIError, some Data helpers

**NotImplementedError** — Genuinely impossible operations that have no Stata
command or C API equivalent (e.g., StrL writeBytes/storeBytes/allocateStrL
require embedded-Python-only _stpy_* functions).

Hardcoded Offsets Eliminated
-----------------------------
All hardcoded function addresses have been replaced with manifest lookups:
  - _OBS_ADDR_RELATIVE -> call_double("_bist_nobs"), call_double("_bist_nvar")
  - _stscalsave -> _sym_addr("_stscalsave")
  - _xgso_newcp_fast_code -> _sym_addr("_xgso_newcp_fast_code")
  - _put_xgso_scalar -> _sym_addr("_put_xgso_scalar")

Runtime data offsets (stack pointer, error address) are auto-discovered
from _pushdbl / _st_store_u ARM64 disassembly via capstone and baked into
the shipped manifest (or auto-detected on first import for unknown versions).

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

# x86_64 platform detection (used for architecture-specific dispatch)
_IS_X86_64 = sys.platform in ("linux", "linux2") and platform.machine() in ("x86_64", "amd64")

# Fast C extension path — lazy import, checked at call time
_fast_path = None  # Will be set to module on first use

def _check_fast_path():
    """Return True if the C fast _bist_* path is available."""
    global _fast_path
    if _fast_path is None:
        try:
            import pystata_x._stata_fast
            _fast_path = pystata_x._stata_fast
        except ImportError:
            _fast_path = False
    if _fast_path:
        return _fast_path._bist_configured and _fast_path._ctx is not None
    return False


logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════
# Macro
def _escape_display(s: str) -> str:
    """Escape a string for safe display in Stata."""
    if not s:
        return ''
    s = s.replace('"', '""')
    return s


def _matrix_name(name: str) -> str:
    """Return a validated Stata-compatible matrix name."""
    if not name or not name.strip():
        raise ValueError('matrix name cannot be empty')
    return name.strip()


# ═══════════════════════════════════════════
class Macro:
    @staticmethod
    def getGlobal(name: str) -> str:
        """Get the value of a Stata global macro."""
        if _check_fast_path():
            return _fast_path.get_macro(name)
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
        if _check_fast_path():
            return int(_fast_path.get_nobs())
        return read_obs_count()

    @staticmethod
    def getVarCount() -> int:
        """Number of variables in the current dataset."""
        if _check_fast_path():
            return int(_fast_path.get_nvar())
        return read_var_count()

    @staticmethod
    def getVarName(varno: int) -> str:
        """Get the name of a variable by its Python index (0-based)."""
        # On x86_64, bypass C fast path (dispatch convention differs)
        if _IS_X86_64:
            try:
                from pystata_x.sfi._engine import _read_var_name_x86
                return _read_var_name_x86(varno)
            except Exception:
                pass
        if _check_fast_path():
            result = _fast_path.get_varname(varno + 1)
            if result:
                return result
        return call_string("_bist_varname", varno + 1)

    @staticmethod
    def getVarLabel(varno: int) -> str:
        """Get the label of a variable by its Python index (0-based)."""
        # On x86_64, bypass C fast path, use name+_bist_varlabel
        if _IS_X86_64:
            try:
                name = Data.getVarName(varno)
                if name:
                    r = call_string("_bist_varlabel", name.encode())
                    return r or ""
            except Exception:
                pass
            return ""
        if _check_fast_path():
            result = _fast_path.get_varlabel(varno + 1)
            if result:
                return result
        return call_string("_bist_varlabel", varno + 1)

    @staticmethod
    def getVarType(varno: int) -> str:
        """Get the storage type of a Stata variable, e.g. 'str18', 'strL', 'double', 'int', 'byte', 'long', 'float'."""
        # On x86_64, bypass C fast path (dispatch convention differs)
        if _IS_X86_64:
            try:
                from pystata_x.sfi._engine import _read_var_type_x86
                return _read_var_type_x86(varno)
            except Exception:
                pass
        if _check_fast_path():
            result = _fast_path.get_vartype(varno + 1)
            if result:
                return result
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
        if _check_fast_path():
            return _fast_path.get_double(obs + 1, varno + 1)
        return call_double("_bist_data", obs + 1, varno + 1)

    @staticmethod
    def getString(varno: int, obs: int) -> str:
        """Read a string value from a cell.

        Uses ``_fast_path.get_string()`` when the C extension is
        available.  Falls back to the Python push+stack path.
        On x86_64, the dispatch function for ``_bist_sdata`` may
        crash under QEMU — in that case return empty string.
        """
        if _check_fast_path():
            try:
                result = _fast_path.get_string(obs + 1, varno + 1)
                if result:
                    return result
            except Exception:
                pass
            except BaseException:
                pass  # SIGSEGV cannot be caught; if we reach here, C ext returned ""
        try:
            return call_string("_bist_sdata", obs + 1, varno + 1) or ""
        except Exception:
            return ""

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
        """Get the maximum variables (Stata SE/MP default)."""
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
        """Add a variable of type strL to the current dataset via executeCommand."""
        from pystata_x.sfi._engine import execute as _exec
        out, rc = _exec(f'generate strL {name} = ""')
        if rc != 0:
            raise RuntimeError(f'addVarStrL failed: {out.strip()}')
        return Data.getVarIndex(name)

    @staticmethod
    def allocateStrL(sc: 'StrLConnector', size: int, binary: bool = True) -> None:
        """Allocate a strL buffer.

        Only _stpy_allocatestrl exists (segfaults via ctypes).
        No Stata command equivalent found.
        """
        raise NotImplementedError(
            'allocateStrL: only _stpy_allocatestrl exists (segfaults). '
            'No Stata command equivalent found '
            '- see REMAINING_GAPS.md for details.'
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

        No _bist_* function found for strL writes.
        Only _stpy* functions exist (segfault via ctypes).
        """
        raise NotImplementedError(
            'writeBytes: only _stpy* functions exist for strL writing, '
            'which segfault via ctypes. No Stata command equivalent found.'
        )

    @staticmethod
    def storeBytes(sc: 'StrLConnector', b: bytes, binary: bool = True):
        """Store bytes in a strL cell.

        No _bist_* function found for strL writes.
        Only _stpy* functions exist (segfault via ctypes).
        """
        raise NotImplementedError(
            'storeBytes: only _stpy* functions exist for strL writing, '
            'which segfault via ctypes. No Stata command equivalent found.'
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
        if _check_fast_path():
            return _fast_path.get_scalar(name)
        return call_double("_bist_numscalar", name.encode())

    @staticmethod
    def setValue(name: str, value: float) -> None:
        """Set a numeric scalar via _stscalsave C function."""
        call_set_scalar(name, value)

    @staticmethod
    def getString(name: str) -> str:
        """Get the value of a string scalar."""
        if _check_fast_path():
            return _fast_path.get_scalar_str(name)
        return call_string("_bist_strscalar", name.encode())

    @staticmethod
    def setString(name: str, value: str) -> None:
        """Set a string scalar via _xgso_newcp_fast_code + _put_xgso_scalar."""
        call_set_strscalar(name, value)


# ═══════════════════════════════════════════
# Missing
# ═══════════════════════════════════════════
class Missing:
    """Stata missing value utilities."""

    _SV_missing = 8.98846567431158e+307
    _EXTENDED_NAMES = [".", ".a", ".b", ".c", ".d", ".e", ".f", ".g", ".h",
                       ".i", ".j", ".k", ".l", ".m", ".n", ".o", ".p", ".q",
                       ".r", ".s", ".t", ".u", ".v", ".w", ".x", ".y", ".z"]
    # Extended missing values differ by 1 ULP (unit in the last place)
    import struct as _struct
    _SV_BITS = _struct.unpack(">Q", _struct.pack(">d", _SV_missing))[0]
    _EXTENDED_VALUES = {}
    _VALUE_TO_NAME = {}
    for _i, _name in enumerate(_EXTENDED_NAMES):
        _bits = _SV_BITS + _i
        _val = _struct.unpack(">d", _struct.pack(">Q", _bits))[0]
        _EXTENDED_VALUES[_name] = _val
        _VALUE_TO_NAME[_val] = _name
    del _struct, _i, _bits, _val

    @staticmethod
    def isMissing(value: float) -> bool:
        import math
        return math.isnan(value) or value < -1e307 or value > 1e307

    @staticmethod
    def getValue(val: str | None = None) -> float:
        if val is None:
            return Missing._SV_missing
        val = val.strip().lower()
        if val in Missing._EXTENDED_VALUES:
            return Missing._EXTENDED_VALUES[val]
        raise ValueError(f"val must be one of {Missing._EXTENDED_NAMES}")

    @staticmethod
    def getMissing(value: float) -> str | None:
        if not Missing.isMissing(value):
            return None
        return Missing._VALUE_TO_NAME.get(value)

    @staticmethod
    def parseIsMissing(s: str) -> bool:
        s = s.strip()
        if s in Missing._EXTENDED_NAMES:
            return True
        try:
            v = float(s)
            return Missing.isMissing(v)
        except ValueError:
            return False
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
    def __init__(self):
        pass

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

    # ── Display methods (via executeCommand) ──────────────────

    @staticmethod
    def display(s: str, asis: bool = False) -> None:
        """Output a string to the Stata Results window.

        Uses executeCommand with display command.
        """
        SFIToolkit.executeCommand(f'display as text "{_escape_display(s)}"')

    @staticmethod
    def displayln(s: str, asis: bool = False) -> None:
        """Output a string to the Stata Results window with newline."""
        SFIToolkit.executeCommand(f'display as text "{_escape_display(s)}"')

    @staticmethod
    def errprint(s: str, asis: bool = False) -> None:
        """Output a string to the Stata Results window as error."""
        SFIToolkit.executeCommand(f'display as error "{_escape_display(s)}"')

    @staticmethod
    def errprintln(s: str, asis: bool = False) -> None:
        """Output an error string with newline."""
        SFIToolkit.executeCommand(f'display as error "{_escape_display(s)}"')

    @staticmethod
    def errprintDebug(s: str, asis: bool = False) -> None:
        """Output a debug string."""
        SFIToolkit.executeCommand(f'display as error "{_escape_display(s)}"')

    @staticmethod
    def errprintlnDebug(s: str, asis: bool = False) -> None:
        """Output a debug string with newline."""
        SFIToolkit.executeCommand(f'display as error "{_escape_display(s)}"')

    @staticmethod
    def formatValue(value: float, fmt: str) -> str:
        """Format a value using a Stata display format.

        Uses executeCommand to format the value via Stata's string() function.
        """
        SFIToolkit.executeCommand(f'local __pv = string({value},{fmt})')
        r = call_string('_bist_global', b'__pv')
        return r if r else ''

    @staticmethod
    def listReturn(cat: str, subcat: str = None) -> list:
        """List return values from Stata (e-, r-, s-, or c- returns).

        Uses executeCommand with return list commands, then reads known
        return values via _bist_global.
        """
        cmd = f'{cat}return list'
        SFIToolkit.executeCommand(cmd)
        # Try to capture common return values via macros
        # For e-class: read e(N), e(g), e(rank), e(F), e(r2), e(rmse), e(mss), e(rss)
        results = []
        for macro in ['level', 'N', 'g', 'rank', 'F', 'r2', 'rmse', 'mss', 'rss',
                       'N_missing', 'N_sumW', 'k', 'df_r', 'df_m', 'll', 'N_clust',
                       'title', 'depvar', 'cmd', 'predict', 'model']:
            r = call_string('_bist_global', f'{cat}({macro})'.encode())
            if r:
                results.append((macro, r))
        return results

    @staticmethod
    def getValue(val: float = None) -> float:
        """Return a value as a Stata-consistent float.

        Same as Missing.getValue().
        """
        from pystata_x.sfi._core import Missing
        if val is None:
            return Missing.getValue()
        return val

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
        """Set a characteristic for the current dataset via executeCommand."""
        from pystata_x.sfi._engine import execute as _exec
        escaped_value = value.replace('"', '""')
        _exec(f'char define [dta] {name} "{escaped_value}"')

    @staticmethod
    def setVariableChar(var: str or int, name: str, value: str) -> None:
        """Set a variable characteristic via executeCommand."""
        from pystata_x.sfi._engine import execute as _exec
        if isinstance(var, int):
            from pystata_x.sfi._core import Data
            var_name = Data.getVarName(var)
        else:
            var_name = var
        escaped_value = value.replace('"', '""')
        _exec(f'char define {var_name}[{name}] "{escaped_value}"')


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
# Helper functions for Matrix/Mata (executeCommand-based)
# ═══════════════════════════════════════════


def _check_all(iterable):
    """Check that all elements in an iterable are truthy."""
    return all(iterable)


def _check_numpy_availability():
    """Raise ModuleNotFoundError if numpy is not available."""
    try:
        import numpy  # noqa: F401
    except ImportError:
        raise ModuleNotFoundError(
            "numpy is not installed. Install it via: pip install numpy"
        )


def _matrix_exec(cmd: str) -> None:
    """Execute a Stata command for matrix/mata operations.

    Uses StataSO_Execute (executeCommand) since the _bist_matrix* C functions
    operate on Stata's internal bytecode dispatch system (not user matrices)
    and corrupt state when called directly.
    """
    from pystata_x.sfi._engine import execute as _exec
    _exec(cmd)


def _matrix_get_local(name: str) -> str:
    """Read a Stata local macro value (set by a previous executeCommand)."""
    r = call_string("_bist_global", name.encode())
    return r if r else ''


def _matrix_get_int_local(name: str) -> int:
    """Read a Stata local macro and parse as int."""
    r = _matrix_get_local(name).strip()
    try:
        return int(r) if r else 0
    except (ValueError, TypeError):
        return 0


def _matrix_get_float_local(name: str) -> float:
    """Read a Stata local macro and parse as float."""
    r = _matrix_get_local(name).strip()
    try:
        return float(r) if r else float('nan')
    except (ValueError, TypeError):
        return float('nan')


def _matrix_name_validate(name: str) -> str:
    """Validate and return a Stata matrix name."""
    if not name or not name.strip():
        raise ValueError('matrix name cannot be empty')
    return name.strip()


def _get_matrix_index(index, name, nrows, ncols, bRow):
    """Normalize row/col index specification for Matrix into a list of ints.

    Parameters
    ----------
    index : int, str, list, tuple, or iterable
        Row or column specification.
        int: single index (supports negative indexing).
        str: space-separated list of row/column names.
        list/tuple of ints: list of indices.
        list/tuple of strings: list of names.
    name : str
        Matrix name (used for name lookups).
    nrows : int
        Number of rows (for range validation).
    ncols : int
        Number of columns (for range validation).
    bRow : bool
        True if indexing rows, False if indexing columns.
    """
    if isinstance(index, int):
        if bRow:
            if index < -nrows or index >= nrows:
                raise ValueError(f"{index}: row index out of range")
        else:
            if index < -ncols or index >= ncols:
                raise ValueError(f"{index}: column index out of range")
        return [index]
    elif isinstance(index, str):
        oret = []
        oindex = index.split()
        if bRow:
            rowNames = Matrix.getRowNames(name)
            for o in oindex:
                try:
                    orowi = rowNames.index(o)
                except ValueError:
                    raise ValueError(f"row {o} not found")
                oret.append(orowi)
        else:
            colNames = Matrix.getColNames(name)
            for o in oindex:
                try:
                    ocoli = colNames.index(o)
                except ValueError:
                    raise ValueError(f"column {o} not found")
                oret.append(ocoli)
        return oret
    elif isinstance(index, (list, tuple)):
        if _check_all(isinstance(o, int) for o in index):
            oret = []
            for o in index:
                if bRow:
                    if o < -nrows or o >= nrows:
                        raise ValueError(f"{o}: row index out of range")
                else:
                    if o < -ncols or o >= ncols:
                        raise ValueError(f"{o}: column index out of range")
                oret.append(o)
            return oret
        elif _check_all(isinstance(o, str) for o in index):
            oret = []
            if bRow:
                rowNames = Matrix.getRowNames(name)
                for o in index:
                    try:
                        orowi = rowNames.index(o)
                    except ValueError:
                        raise ValueError(f"row {o} not found")
                    oret.append(orowi)
            else:
                colNames = Matrix.getColNames(name)
                for o in index:
                    try:
                        ocoli = colNames.index(o)
                    except ValueError:
                        raise ValueError(f"column {o} not found")
                    oret.append(ocoli)
            return oret
        else:
            raise TypeError("all values for row or column indices must be a string or an integer")
    elif hasattr(index, "__iter__"):
        index = tuple(index)
        if _check_all(isinstance(o, int) for o in index):
            oret = []
            for o in index:
                if bRow:
                    if o < -nrows or o >= nrows:
                        raise ValueError(f"{o}: row index out of range")
                else:
                    if o < -ncols or o >= ncols:
                        raise ValueError(f"{o}: column index out of range")
                oret.append(o)
            return oret
        elif _check_all(isinstance(o, str) for o in index):
            oret = []
            if bRow:
                rowNames = Matrix.getRowNames(name)
                for o in index:
                    try:
                        orowi = rowNames.index(o)
                    except ValueError:
                        raise ValueError(f"row {o} not found")
                    oret.append(orowi)
            else:
                colNames = Matrix.getColNames(name)
                for o in index:
                    try:
                        ocoli = colNames.index(o)
                    except ValueError:
                        raise ValueError(f"column {o} not found")
                    oret.append(ocoli)
            return oret
        else:
            raise TypeError("all values for row or column indices must be a string or an integer")
    else:
        raise TypeError("unsupported operand type(s) for row or column indices")


def _get_mata_index(index, nrows, ncols, bRow):
    """Normalize row/col index specification for Mata into a list of ints.

    Similar to _get_matrix_index but Mata uses direct row/col counts
    (no name lookup since Mata does not have row/col names natively).
    """
    if isinstance(index, int):
        if bRow:
            if index < -nrows or index >= nrows:
                raise ValueError(f"{index}: row index out of range")
        else:
            if index < -ncols or index >= ncols:
                raise ValueError(f"{index}: column index out of range")
        return [index]
    elif isinstance(index, (list, tuple)):
        if _check_all(isinstance(o, int) for o in index):
            oret = []
            for o in index:
                if bRow:
                    if o < -nrows or o >= nrows:
                        raise ValueError(f"{o}: row index out of range")
                else:
                    if o < -ncols or o >= ncols:
                        raise ValueError(f"{o}: column index out of range")
                oret.append(o)
            return oret
        else:
            raise TypeError("all values for row or column indices must be an integer")
    elif hasattr(index, "__iter__"):
        index = tuple(index)
        if _check_all(isinstance(o, int) for o in index):
            oret = []
            for o in index:
                if bRow:
                    if o < -nrows or o >= nrows:
                        raise ValueError(f"{o}: row index out of range")
                else:
                    if o < -ncols or o >= ncols:
                        raise ValueError(f"{o}: column index out of range")
                oret.append(o)
            return oret
        else:
            raise TypeError("all values for row or column indices must be an integer")
    else:
        raise TypeError("unsupported operand type(s) for row or column indices")


# ═══════════════════════════════════════════
# Matrix
# ═══════════════════════════════════════════

class Matrix:
    """Access to Stata matrices.

    All row and column numbering begins at 0. Negative values for row
    and col are allowed and are interpreted in the usual way for Python
    indexing (-1 = last row/col).

    Matrix names can be:
    * global matrix such as "mymatrix"
    * r() matrix such as "r(Z)"
    * e() matrix such as "e(Z)"

    Uses executeCommand for all read/write operations (the _bist_matrix*
    C functions operate on Stata's internal bytecode dispatch system, not
    user-created matrices, and corrupt state when called directly).
    """

    def __init__(self):
        pass

    @staticmethod
    def convertSymmetricToStd(name: str) -> None:
        """Convert a symmetric matrix to a standard matrix.

        Parameters
        ----------
        name : str
            Name of the matrix.

        Raises
        ------
        ValueError
            If matrix `name` does not exist.
        """
        _matrix_name_validate(name)
        if not Matrix.exists(name):
            raise ValueError(f"matrix {name} does not exist")
        _matrix_exec(f'matrix {name} = {name}')

    @staticmethod
    def create(name: str, nrows: int, ncols: int, initialValue: float,
               isSymmetric: bool = False) -> None:
        """Create a Stata matrix.

        Parameters
        ----------
        name : str
            Name of the matrix.
        nrows : int
            Number of rows.
        ncols : int
            Number of columns.
        initialValue : float
            An initialization value for each element.
        isSymmetric : bool, optional
            Mark the matrix as symmetric. Default is False.

        Raises
        ------
        ValueError
            If `nrows` or `ncols` are not positive integers.
        """
        _matrix_name_validate(name)
        if not isinstance(nrows, int) or nrows <= 0:
            raise ValueError("nrows must be a positive integer")
        if not isinstance(ncols, int) or ncols <= 0:
            raise ValueError("ncols must be a positive integer")
        if not isinstance(isSymmetric, bool):
            raise TypeError("isSymmetric must be a boolean value")

        _matrix_exec(f'matrix {name} = J({nrows},{ncols},{initialValue})')
        if isSymmetric and nrows == ncols:
            _matrix_exec(f"matrix {name} = ({name}+{name}')/2")

    @staticmethod
    def fromNPArray(arr, name: str) -> None:
        """Store a NumPy array as a Stata matrix.

        If the Stata matrix `name` already exists, its contents will be
        replaced; otherwise, a new Stata matrix named `name` is created.

        Parameters
        ----------
        arr : numpy.ndarray
            The NumPy array.
        name : str
            Name of the matrix to create.

        Raises
        ------
        ModuleNotFoundError
            If numpy is not installed.
        TypeError
            If the array is not numeric.
        """
        _check_numpy_availability()
        import numpy as np  # noqa: F811

        if not isinstance(arr, np.ndarray):
            raise TypeError("A NumPy array is required.")

        ndim = len(arr.shape)
        if ndim < 1 or ndim >= 3:
            raise TypeError("Dimension of array must not be greater than 2.")

        if not np.issubdtype(arr.dtype, np.number):
            raise TypeError("Only numeric array is allowed.")

        if ndim == 1:
            nrows = 1
            ncols = arr.shape[0]
        else:
            nrows = arr.shape[0]
            ncols = arr.shape[1]

        if arr.size == 0:
            return

        Matrix.create(name, nrows, ncols, float('nan'))
        Matrix.store(name, arr)

    @staticmethod
    def get(name: str, rows=None, cols=None) -> list:
        """Get the data in a Stata matrix.

        Parameters
        ----------
        name : str
            Name of the matrix.
        rows : int or list-like, optional
            Rows to access. If not specified, all rows are specified.
        cols : int or list-like, optional
            Columns to access. If not specified, all columns are specified.

        Returns
        -------
        list
            A list of lists containing the matrix values.

        Raises
        ------
        ValueError
            If matrix `name` does not exist or row/col indices out of range.
        """
        _matrix_name_validate(name)
        ncols = Matrix.getColTotal(name)
        nrows = Matrix.getRowTotal(name)

        if rows is None:
            mrows = list(range(nrows))
        else:
            mrows = _get_matrix_index(rows, name, nrows, ncols, True)

        if cols is None:
            mcols = list(range(ncols))
        else:
            mcols = _get_matrix_index(cols, name, nrows, ncols, False)

        # Convert negative indices to positive
        mrows = [r if r >= 0 else r + nrows for r in mrows]
        mcols = [c if c >= 0 else c + ncols for c in mcols]

        result = []
        for r in mrows:
            row_vals = []
            for c in mcols:
                _matrix_exec(
                    f'local __px_val = {name}[{r + 1},{c + 1}]'
                )
                val_str = _matrix_get_local('__px_val')
                try:
                    val = float(val_str) if val_str else float('nan')
                except (ValueError, TypeError):
                    val = float('nan')
                row_vals.append(val)
            result.append(row_vals)
        return result

    @staticmethod
    def getAt(name: str, row: int, col: int) -> float:
        """Access an element from a Stata matrix.

        Parameters
        ----------
        name : str
            Name of the matrix.
        row : int
            Row to access.
        col : int
            Column to access.

        Returns
        -------
        float
            The value.

        Raises
        ------
        ValueError
            If matrix `name` does not exist or index out of range.
        """
        _matrix_name_validate(name)
        nrows = Matrix.getRowTotal(name)
        ncols = Matrix.getColTotal(name)

        if row < -nrows or row >= nrows:
            raise ValueError(f"{row}: row index out of range")
        if col < -ncols or col >= ncols:
            raise ValueError(f"{col}: column index out of range")

        r = row + 1 if row >= 0 else row + nrows + 1
        c = col + 1 if col >= 0 else col + ncols + 1

        _matrix_exec(f'local __px_at = {name}[{r},{c}]')
        val_str = _matrix_get_local('__px_at')
        try:
            return float(val_str) if val_str else float('nan')
        except (ValueError, TypeError):
            return float('nan')

    @staticmethod
    def getColNames(name: str) -> list:
        """Get the column names of a Stata matrix.

        Parameters
        ----------
        name : str
            Name of the matrix.

        Returns
        -------
        list
            A string list containing the column names.

        Raises
        ------
        ValueError
            If matrix `name` does not exist.
        """
        _matrix_name_validate(name)
        if not Matrix.exists(name):
            raise ValueError(f"matrix {name} does not exist")
        _matrix_exec(f'local __px_cnames : colnames {name}')
        r = _matrix_get_local('__px_cnames').strip()
        return r.split() if r else []

    @staticmethod
    def getColTotal(name: str) -> int:
        """Get the number of columns in a Stata matrix.

        Parameters
        ----------
        name : str
            Name of the matrix.

        Returns
        -------
        int
            The number of columns.

        Raises
        ------
        ValueError
            If matrix `name` does not exist.
        """
        _matrix_name_validate(name)
        _matrix_exec(f'local __px_ncols = colsof({name})')
        n = _matrix_get_int_local('__px_ncols')
        if n == 0:
            raise ValueError(f"matrix {name} does not exist")
        return n

    @staticmethod
    def getRowNames(name: str) -> list:
        """Get the row names of a Stata matrix.

        Parameters
        ----------
        name : str
            Name of the matrix.

        Returns
        -------
        list
            A string list containing the row names.

        Raises
        ------
        ValueError
            If matrix `name` does not exist.
        """
        _matrix_name_validate(name)
        if not Matrix.exists(name):
            raise ValueError(f"matrix {name} does not exist")
        _matrix_exec(f'local __px_rnames : rownames {name}')
        r = _matrix_get_local('__px_rnames').strip()
        return r.split() if r else []

    @staticmethod
    def getRowTotal(name: str) -> int:
        """Get the number of rows in a Stata matrix.

        Parameters
        ----------
        name : str
            Name of the matrix.

        Returns
        -------
        int
            The number of rows.

        Raises
        ------
        ValueError
            If matrix `name` does not exist.
        """
        _matrix_name_validate(name)
        _matrix_exec(f'local __px_nrows = rowsof({name})')
        n = _matrix_get_int_local('__px_nrows')
        if n == 0:
            raise ValueError(f"matrix {name} does not exist")
        return n

    @staticmethod
    def getNames() -> list:
        """Get the names of all Stata matrices.

        Uses _bist_matrix_hcat (this C function returns matrix catalog
        without corrupting state). Falls back to matrix dir if needed.
        """
        r = call_string("_bist_matrix_hcat")
        if r:
            names = [x.strip() for x in r.split() if x.strip()]
            if names:
                return names
        # Fallback: use matrix dir command
        _matrix_exec('matrix dir')
        return []

    @staticmethod
    def exists(name: str) -> bool:
        """Check if a matrix exists.

        Parameters
        ----------
        name : str
            Name of the matrix.

        Returns
        -------
        bool
            True if the matrix exists.
        """
        _matrix_name_validate(name)
        names = Matrix.getNames()
        return name in names

    @staticmethod
    def list(name: str, rows=None, cols=None) -> None:
        """Display a Stata matrix.

        Parameters
        ----------
        name : str
            Name of the matrix.
        rows : int or list-like, optional
            Rows to display.
        cols : int or list-like, optional
            Columns to display.

        Raises
        ------
        ValueError
            If matrix `name` does not exist or row/col indices out of range.
        """
        _matrix_name_validate(name)
        nrows = Matrix.getRowTotal(name)
        ncols = Matrix.getColTotal(name)

        if rows is not None:
            mrows = _get_matrix_index(rows, name, nrows, ncols, True)
            row_str = ' '.join(str(r + 1) for r in mrows)
            _matrix_exec(
                f'matrix __px_list = {name}[{" ".join(str(r+1) for r in mrows)},.]'
            )
            _matrix_exec('matrix list __px_list, nohalf')
        elif cols is not None:
            mcols = _get_matrix_index(cols, name, nrows, ncols, False)
            _matrix_exec(
                f'matrix __px_list = {name}[.,{" ".join(str(c+1) for c in mcols)}]'
            )
            _matrix_exec('matrix list __px_list, nohalf')
        else:
            _matrix_exec(f'matrix list {name}, nohalf')

    @staticmethod
    def setColNames(name: str, colNames) -> None:
        """Set the column names of a Stata matrix.

        Parameters
        ----------
        name : str
            Name of the matrix.
        colNames : list or tuple
            A string list containing the column names.

        Raises
        ------
        ValueError
            If matrix `name` does not exist or name count mismatch.
        """
        _matrix_name_validate(name)
        if not Matrix.exists(name):
            raise ValueError(f"matrix {name} does not exist")
        names_str = ' '.join(str(n) for n in colNames)
        _matrix_exec(f'matrix colnames {name} = {names_str}')

    @staticmethod
    def setRowNames(name: str, rowNames) -> None:
        """Set the row names of a Stata matrix.

        Parameters
        ----------
        name : str
            Name of the matrix.
        rowNames : list or tuple
            A string list containing the row names.

        Raises
        ------
        ValueError
            If matrix `name` does not exist or name count mismatch.
        """
        _matrix_name_validate(name)
        if not Matrix.exists(name):
            raise ValueError(f"matrix {name} does not exist")
        names_str = ' '.join(str(n) for n in rowNames)
        _matrix_exec(f'matrix rownames {name} = {names_str}')

    @staticmethod
    def store(name: str, val) -> None:
        """Store elements in an existing Stata matrix or create a new one.

        Parameters
        ----------
        name : str
            Name of the matrix.
        val : array-like
            Values to store.

        Raises
        ------
        ValueError
            If dimensions do not match.
        TypeError
            If value is a string.
        """
        _matrix_name_validate(name)

        # Check if matrix exists
        mexist = True
        try:
            ncols = Matrix.getColTotal(name)
            nrows = Matrix.getRowTotal(name)
        except ValueError:
            mexist = False

        def listimize(x):
            if isinstance(x, str):
                raise TypeError("Value of matrix cannot be string")
            if not hasattr(x, "__iter__"):
                return [x]
            return list(x)

        if isinstance(val, str):
            raise TypeError("Value of matrix cannot be string")

        if not hasattr(val, "__iter__"):
            val = [[val]]
        else:
            val = list(listimize(v) for v in val)

        if mexist:
            if (nrows == 1 and len(val) == ncols and
                    _check_all(len(v) == 1 for v in val)):
                val = [[v[0] for v in val]]
            if len(val) != nrows:
                raise ValueError("compatibility error; rows unmatch")
            if not _check_all(len(v) == ncols for v in val):
                raise ValueError("compatibility error; columns unmatch")
        else:
            if len(val) <= 0:
                raise ValueError("compatibility error; val is empty")
            ncols = len(val[0])
            if not _check_all(len(v) == ncols for v in val):
                raise ValueError("compatibility error; columns unmatch")
            Matrix.create(name, len(val), ncols, 0.0)

        # Build matrix literal string from val
        rows_str = []
        for row in val:
            row_vals = []
            for v in row:
                if isinstance(v, (int, float)):
                    row_vals.append(str(v))
                else:
                    row_vals.append(str(v))
            rows_str.append(','.join(row_vals))
        matrix_literal = ' \\ '.join(rows_str)
        _matrix_exec(f'matrix {name} = ({matrix_literal})')

    @staticmethod
    def storeAt(name: str, row: int, col: int, val: float) -> None:
        """Store an element in an existing Stata matrix.

        Parameters
        ----------
        name : str
            Name of the matrix.
        row : int
            Row in which to store.
        col : int
            Column in which to store.
        val : float
            Value to store.

        Raises
        ------
        ValueError
            If matrix `name` does not exist or index out of range.
        """
        _matrix_name_validate(name)
        nrows = Matrix.getRowTotal(name)
        ncols = Matrix.getColTotal(name)

        if row < -nrows or row >= nrows:
            raise ValueError(f"{row}: row index out of range")
        if col < -ncols or col >= ncols:
            raise ValueError(f"{col}: column index out of range")

        r = row + 1 if row >= 0 else row + nrows + 1
        c = col + 1 if col >= 0 else col + ncols + 1

        _matrix_exec(f'matrix {name}[{r},{c}] = {val}')

    @staticmethod
    def toNPArray(name: str, rows=None, cols=None):
        """Export values from an existing Stata matrix into a NumPy array.

        Parameters
        ----------
        name : str
            Name of the matrix.
        rows : int or list-like, optional
            Rows to access.
        cols : int or list-like, optional
            Columns to access.

        Returns
        -------
        numpy.ndarray
            The matrix data as a NumPy array.

        Raises
        ------
        ModuleNotFoundError
            If numpy is not installed.
        ValueError
            If matrix `name` does not exist or index out of range.
        """
        _check_numpy_availability()
        import numpy as np  # noqa: F811
        return np.array(Matrix.get(name, rows, cols))

    @staticmethod
    def drop(name: str) -> None:
        """Drop a Stata matrix.

        Parameters
        ----------
        name : str
            Name of the matrix.
        """
        _matrix_name_validate(name)
        _matrix_exec(f'matrix drop {name}')

    # Backward-compatible aliases
    getRowCount = getRowTotal
    getColCount = getColTotal
    set = store


# ═══════════════════════════════════════════
# Mata
# ═══════════════════════════════════════════
class Mata:
    """Access to Stata's Mata matrix system.

    All row and column numbering begins at 0. Negative values for row
    and col are allowed and are interpreted in the usual way for Python
    indexing (-1 = last row/col).

    Uses executeCommand with mata: commands for all operations (no working
    _bist_mata* C functions exist).
    """

    def __init__(self):
        pass

    @staticmethod
    def create(name: str, nrows: int, ncols: int, initialValue) -> None:
        """Create a Mata matrix.

        Parameters
        ----------
        name : str
            Name of the matrix.
        nrows : int
            Number of rows.
        ncols : int
            Number of columns.
        initialValue : float, str, or complex
            An initialization value for each element.
            float -> real matrix, str -> string matrix, complex -> complex matrix.

        Raises
        ------
        ValueError
            If `nrows` or `ncols` are not positive integers.
        """
        if not isinstance(nrows, int) or nrows <= 0:
            raise ValueError("nrows must be a positive integer")
        if not isinstance(ncols, int) or ncols <= 0:
            raise ValueError("ncols must be a positive integer")

        if isinstance(initialValue, str):
            escaped = initialValue.replace('"', '\\"')
            _matrix_exec(f'mata: {name} = J({nrows},{ncols},"{escaped}")')
        elif isinstance(initialValue, complex):
            _matrix_exec(f'mata: {name} = J({nrows},{ncols},{initialValue.real}+{initialValue.imag}i)')
        else:
            _matrix_exec(f'mata: {name} = J({nrows},{ncols},{initialValue})')

    @staticmethod
    def fromNPArray(arr, name: str) -> None:
        """Store a NumPy array as a Mata matrix.

        Parameters
        ----------
        arr : numpy.ndarray
            The NumPy array.
        name : str
            Name of the Mata matrix to create.

        Raises
        ------
        ModuleNotFoundError
            If numpy is not installed.
        TypeError
            If the array is not of a supported type.
        """
        _check_numpy_availability()
        import numpy as np  # noqa: F811

        if not isinstance(arr, np.ndarray):
            raise TypeError("A NumPy array is required.")

        ndim = len(arr.shape)
        if ndim < 1 or ndim >= 3:
            raise TypeError("Dimension of array must not be greater than 2.")

        dtype = arr.dtype.name
        if dtype in ('bool_', 'bool8', 'byte', 'short', 'intc', 'int8', 'int16',
                     'int32', 'int_', 'longlong', 'intp', 'int64', 'uint',
                     'uint8', 'uint16', 'uint32', 'uint64', 'half', 'single',
                     'float16', 'float32', 'double', 'float_', 'longfloat',
                     'float64'):
            dtypestr = 'real'
        elif dtype in ('csingle', 'cdouble', 'clongdouble', 'complex64',
                       'complex128', 'complex_'):
            dtypestr = 'complex'
        else:
            dtypestr = 'string'

        nobs = len(arr)
        if nobs == 0:
            return

        if ndim == 1:
            nrows = 1
            ncols = nobs
        else:
            nrows = arr.shape[0]
            ncols = arr.shape[1]

        if dtypestr == 'real':
            Mata.create(name, nrows, ncols, float('nan'))
        elif dtypestr == 'complex':
            Mata.create(name, nrows, ncols, 0j)
        else:
            Mata.create(name, nrows, ncols, '')

        Mata.store(name, arr)

    @staticmethod
    def get(name: str, rows=None, cols=None) -> list:
        """Access elements from a Mata matrix.

        Parameters
        ----------
        name : str
            Name of the Mata matrix.
        rows : int or list-like, optional
            Rows to access.
        cols : int or list-like, optional
            Columns to access.

        Returns
        -------
        list
            A list of lists containing the matrix values.

        Raises
        ------
        ValueError
            If matrix `name` does not exist or index out of range.
        """
        ncols = Mata.getColTotal(name)
        nrows = Mata.getRowTotal(name)

        if rows is None:
            mrows = list(range(nrows))
        else:
            mrows = _get_mata_index(rows, nrows, ncols, True)

        if cols is None:
            mcols = list(range(ncols))
        else:
            mcols = _get_mata_index(cols, nrows, ncols, False)

        mrows = [r if r >= 0 else r + nrows for r in mrows]
        mcols = [c if c >= 0 else c + ncols for c in mcols]

        eltype = Mata.getEltype(name)
        result = []
        for r in mrows:
            row_vals = []
            for c in mcols:
                if eltype == 'string':
                    _matrix_exec(f'mata: st_local("__px_val", {name}[{r + 1},{c + 1}])')
                    val_str = _matrix_get_local('__px_val')
                    row_vals.append(val_str)
                elif eltype == 'complex':
                    _matrix_exec(f'mata: st_numscalar("__px_val", Re({name}[{r + 1},{c + 1}]))')
                    _matrix_exec(f'mata: st_numscalar("__px_vali", Im({name}[{r + 1},{c + 1}]))')
                    re_val = call_double("_bist_numscalar", b'__px_val')
                    im_val = call_double("_bist_numscalar", b'__px_vali')
                    row_vals.append(complex(re_val or float('nan'), im_val or float('nan')))
                else:
                    _matrix_exec(f'mata: st_numscalar("__px_val", {name}[{r + 1},{c + 1}])')
                    val = call_double("_bist_numscalar", b'__px_val')
                    row_vals.append(val if val is not None else float('nan'))
            result.append(row_vals)
        return result

    @staticmethod
    def getAt(name: str, row: int, col: int):
        """Access an element from a Mata matrix.

        Parameters
        ----------
        name : str
            Name of the Mata matrix.
        row : int
            Row to access.
        col : int
            Column to access.

        Returns
        -------
        float, str, or complex
            The value.

        Raises
        ------
        ValueError
            If matrix `name` does not exist or index out of range.
        """
        nrows = Mata.getRowTotal(name)
        ncols = Mata.getColTotal(name)

        if row < -nrows or row >= nrows:
            raise ValueError(f"{row}: row index out of range")
        if col < -ncols or col >= ncols:
            raise ValueError(f"{col}: column index out of range")

        r = row + 1 if row >= 0 else row + nrows + 1
        c = col + 1 if col >= 0 else col + ncols + 1

        eltype = Mata.getEltype(name)
        if eltype == 'string':
            _matrix_exec(f'mata: st_local("__px_at", {name}[{r},{c}])')
            return _matrix_get_local('__px_at')
        elif eltype == 'complex':
            _matrix_exec(f'mata: st_numscalar("__px_at_re", Re({name}[{r},{c}]))')
            _matrix_exec(f'mata: st_numscalar("__px_at_im", Im({name}[{r},{c}]))')
            re_val = call_double("_bist_numscalar", b'__px_at_re')
            im_val = call_double("_bist_numscalar", b'__px_at_im')
            return complex(re_val or float('nan'), im_val or float('nan'))
        else:
            _matrix_exec(f'mata: st_numscalar("__px_at", {name}[{r},{c}])')
            val = call_double("_bist_numscalar", b'__px_at')
            return val if val is not None else float('nan')

    @staticmethod
    def getColTotal(name: str) -> int:
        """Get the number of columns in a Mata matrix.

        Parameters
        ----------
        name : str
            Name of the Mata matrix.

        Returns
        -------
        int
            The number of columns.

        Raises
        ------
        ValueError
            If object `name` does not exist.
        """
        _matrix_exec(f'mata: st_numscalar("__px_nc", cols({name}))')
        n = call_double("_bist_numscalar", b'__px_nc')
        if n is None:
            raise ValueError(f"Mata object {name} does not exist")
        return int(n)

    @staticmethod
    def getEltype(name: str) -> str:
        """Get the element type of a Mata object.

        Parameters
        ----------
        name : str
            Name of the Mata object.

        Returns
        -------
        str
            The eltype: "real", "complex", or "string".

        Raises
        ------
        ValueError
            If object `name` does not exist.
        """
        _matrix_exec(f'mata: st_local("__px_eltype", eltype({name}))')
        r = _matrix_get_local('__px_eltype').strip()
        if not r:
            raise ValueError(f"Mata object {name} does not exist")
        return r

    @staticmethod
    def getRowTotal(name: str) -> int:
        """Get the number of rows in a Mata matrix.

        Parameters
        ----------
        name : str
            Name of the Mata matrix.

        Returns
        -------
        int
            The number of rows.

        Raises
        ------
        ValueError
            If object `name` does not exist.
        """
        _matrix_exec(f'mata: st_numscalar("__px_nr", rows({name}))')
        n = call_double("_bist_numscalar", b'__px_nr')
        if n is None:
            raise ValueError(f"Mata object {name} does not exist")
        return int(n)

    @staticmethod
    def isTypeComplex(name: str) -> bool:
        """Determine if the Mata object type is complex.

        Parameters
        ----------
        name : str
            Name of the Mata object.

        Returns
        -------
        bool
            True if complex.

        Raises
        ------
        ValueError
            If object `name` does not exist.
        """
        return Mata.getEltype(name) == "complex"

    @staticmethod
    def isTypeReal(name: str) -> bool:
        """Determine if the Mata object type is real.

        Parameters
        ----------
        name : str
            Name of the Mata object.

        Returns
        -------
        bool
            True if real.

        Raises
        ------
        ValueError
            If object `name` does not exist.
        """
        return Mata.getEltype(name) == "real"

    @staticmethod
    def isTypeString(name: str) -> bool:
        """Determine if the Mata object type is string.

        Parameters
        ----------
        name : str
            Name of the Mata object.

        Returns
        -------
        bool
            True if string.

        Raises
        ------
        ValueError
            If object `name` does not exist.
        """
        return Mata.getEltype(name) == "string"

    @staticmethod
    def list(name: str, rows=None, cols=None) -> None:
        """Display a Mata matrix.

        Parameters
        ----------
        name : str
            Name of the Mata matrix.
        rows : int or list-like, optional
            Rows to display.
        cols : int or list-like, optional
            Columns to display.

        Raises
        ------
        ValueError
            If matrix `name` does not exist or index out of range.
        """
        ncols = Mata.getColTotal(name)
        nrows = Mata.getRowTotal(name)

        if rows is not None:
            mrows = _get_mata_index(rows, nrows, ncols, True)
            maxrow = max(mrows)
        else:
            maxrow = nrows - 1
        if cols is not None:
            mcols = _get_mata_index(cols, nrows, ncols, False)
            maxcol = max(mcols)
        else:
            maxcol = ncols - 1

        _matrix_exec(f'mata: {name}')

    @staticmethod
    def store(name: str, val) -> None:
        """Store elements in an existing Mata matrix.

        Parameters
        ----------
        name : str
            Name of the matrix.
        val : array-like
            Values to store.

        Raises
        ------
        ValueError
            If dimensions do not match.
        """
        nrows = Mata.getRowTotal(name)
        ncols = Mata.getColTotal(name)

        def listimize(x):
            if isinstance(x, str) or not hasattr(x, "__iter__"):
                return [x]
            return list(x)

        if isinstance(val, str) or not hasattr(val, "__iter__"):
            val = [[val]]
        else:
            val = list(listimize(v) for v in val)

        if (nrows == 1 and len(val) == ncols and
                _check_all(len(v) == 1 for v in val)):
            val = [[v[0] for v in val]]

        if len(val) != nrows:
            raise ValueError("compatibility error; rows unmatch")
        if not _check_all(len(v) == ncols for v in val):
            raise ValueError("compatibility error; columns unmatch")

        # Build Mata literal matrix string
        rows_str = []
        for row in val:
            row_vals = []
            for v in row:
                if isinstance(v, str):
                    escaped = v.replace('"', '\\"')
                    row_vals.append(f'"{escaped}"')
                elif isinstance(v, complex):
                    row_vals.append(f'{v.real}+{v.imag}i')
                else:
                    row_vals.append(str(v))
            rows_str.append(','.join(row_vals))
        matrix_literal = '\\'.join(rows_str)
        _matrix_exec(f'mata: {name} = ({matrix_literal})')

    @staticmethod
    def storeAt(name: str, row: int, col: int, val) -> None:
        """Store an element in an existing Mata matrix.

        Parameters
        ----------
        name : str
            Name of the matrix.
        row : int
            Row in which to store.
        col : int
            Column in which to store.
        val : float, str, or complex
            Value to store.

        Raises
        ------
        ValueError
            If matrix `name` does not exist or index out of range.
        """
        nrows = Mata.getRowTotal(name)
        ncols = Mata.getColTotal(name)

        if row < -nrows or row >= nrows:
            raise ValueError(f"{row}: row index out of range")
        if col < -ncols or col >= ncols:
            raise ValueError(f"{col}: column index out of range")

        r = row + 1 if row >= 0 else row + nrows + 1
        c = col + 1 if col >= 0 else col + ncols + 1

        if isinstance(val, str):
            escaped = val.replace('"', '\\"')
            _matrix_exec(f'mata: {name}[{r},{c}] = "{escaped}"')
        elif isinstance(val, complex):
            _matrix_exec(f'mata: {name}[{r},{c}] = {val.real}+{val.imag}i')
        else:
            _matrix_exec(f'mata: {name}[{r},{c}] = {val}')

    @staticmethod
    def toNPArray(name: str, rows=None, cols=None):
        """Export values from an existing Mata matrix into a NumPy array.

        Parameters
        ----------
        name : str
            Name of the matrix.
        rows : int or list-like, optional
            Rows to access.
        cols : int or list-like, optional
            Columns to access.

        Returns
        -------
        numpy.ndarray
            The matrix data as a NumPy array.

        Raises
        ------
        ModuleNotFoundError
            If numpy is not installed.
        ValueError
            If matrix `name` does not exist or index out of range.
        """
        _check_numpy_availability()
        import numpy as np  # noqa: F811

        rowtotal = Mata.getRowTotal(name)
        coltotal = Mata.getColTotal(name)
        if rowtotal == 0 or coltotal == 0:
            if Mata.isTypeString(name):
                return np.empty((rowtotal, coltotal), dtype=str)
            elif Mata.isTypeComplex(name):
                return np.empty((rowtotal, coltotal), dtype='complex')
            else:
                return np.empty((rowtotal, coltotal))
        else:
            return np.array(Mata.get(name, rows, cols))

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
        from pystata_x.sfi._engine import _restore_sp, _STACK_PTR_OFFSET, _SYMS

        sp_addr = _BASE + _STACK_PTR_OFFSET
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
        return Data.getMaxVars()

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

    def fromNPArray(self, arr, prefix='v', force=False) -> 'Frame':
        """Load a NumPy array into this Frame, making it the current dataset.

        Makes this frame current, then delegates to Data.fromNPArray.

        Parameters
        ----------
        arr : numpy.ndarray
            The NumPy array.
        prefix : str, optional
            Prefix for variable names (default 'v').
        force : bool, optional
            Force loading even if data unsaved (default False).

        Returns
        -------
        Frame
            Self, for chaining.
        """
        self.changeToCWF()
        Data.fromNPArray(arr, prefix=prefix, force=force)
        return self

    def fromPDataFrame(self, df, force=False) -> 'Frame':
        """Load a pandas DataFrame into this Frame, making it current.

        Makes this frame current, then delegates to Data.fromPDataFrame.

        Parameters
        ----------
        df : pandas.DataFrame
            The DataFrame.
        force : bool, optional
            Force loading even if data unsaved (default False).

        Returns
        -------
        Frame
            Self, for chaining.
        """
        self.changeToCWF()
        Data.fromPDataFrame(df, force=force)
        return self
