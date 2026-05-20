"""x86_64 Stata data reader — output-buffer-based fallback.

When the _bist_* dispatch path crashes or returns sentinel values on
x86_64, this module provides a working fallback via ``StataSO_Execute``
with output-buffer parsing.  All results are cached to avoid repeated
Stata calls.

Three access patterns are supported:

1. Numeric cell read:  display <varname>[<obs>]   → float
2. String cell read:   display <varname>[<obs>]   → str (string var)
3. Scalar read:        display scalar(<name>)     → float
4. Scalar string:      display scalar(<name>)     → str
5. Macro read:         display "`<name>'"          → str
6. Macro write:        global <name> <value>       → None
7. Value label:        label list <name>           → parsed dict

"""

import ctypes
import logging
from typing import Optional, Any

log = logging.getLogger(__name__)

_X86_DISPLAY_BUF_INIT = False
_OUTPUT_CACHE: dict[str, Any] = {}


def _ensure_output_buf(eng) -> None:
    """Initialise the Stata output buffer (64 KiB)."""
    global _X86_DISPLAY_BUF_INIT
    if not _X86_DISPLAY_BUF_INIT and eng is not None:
        try:
            eng.StataSO_SetOutputBufferSz.restype = None
            eng.StataSO_SetOutputBufferSz.argtypes = [ctypes.c_size_t]
            eng.StataSO_SetOutputBufferSz(65536)
            eng.StataSO_ClearOutputBuffer.restype = None
            _X86_DISPLAY_BUF_INIT = True
        except AttributeError:
            pass


def _get_engine_lib():
    """Lazy import of the engine module to get the current Stata CDLL."""
    import pystata_x.sfi._engine as eng_mod
    return eng_mod._LIB


def _exec(cmd: str | bytes) -> Optional[str]:
    """Execute a Stata command and return the cleaned output, or None."""
    if isinstance(cmd, str):
        cmd = cmd.encode("utf-8", errors="replace")
    eng = _get_engine_lib()
    if eng is None:
        return None
    _ensure_output_buf(eng)
    try:
        eng.StataSO_ClearOutputBuffer()
        rc = eng.StataSO_Execute(cmd)
        if rc != 0:
            return None
        buf = eng.StataSO_GetOutputBuffer
        buf.restype = ctypes.c_char_p
        out = buf()
        if out is None:
            return None
        text = out.decode("utf-8", errors="replace")
        # Return the last non-empty, non-prompt line (preserve leading whitespace)
        for line in reversed(text.split("\n")):
            stripped = line.strip()
            if stripped and not stripped.startswith(".") and not stripped.startswith("."):
                return line
        return None
    except Exception:
        log.exception("x86 display exec failed")
        return None


def _exec_all(cmd: str | bytes) -> list[str] | None:
    """Execute a Stata command and return ALL non-prompt output lines."""
    if isinstance(cmd, str):
        cmd = cmd.encode("utf-8", errors="replace")
    eng = _get_engine_lib()
    if eng is None:
        return None
    _ensure_output_buf(eng)
    try:
        eng.StataSO_ClearOutputBuffer()
        rc = eng.StataSO_Execute(cmd)
        if rc != 0:
            return None
        buf = eng.StataSO_GetOutputBuffer
        buf.restype = ctypes.c_char_p
        out = buf()
        if out is None:
            return None
        text = out.decode("utf-8", errors="replace")
        lines: list[str] = []
        for line in text.split("\n"):
            stripped = line.strip()
            if stripped and not stripped.startswith(".") and not stripped.startswith(">"):
                lines.append(line)
        return lines if lines else None
    except Exception:
        log.exception("x86 display exec_all failed")
        return None


# ─── Numeric data cell ──────────────────────────────────────────────────


_NUMERIC_DATA_CACHE: dict[tuple[int, int], float] = {}


def read_double(varno: int, obs: int) -> float:
    """Read a numeric cell via ``display <varname>[<obs+1>]``."""
    key = (varno, obs)
    cached = _NUMERIC_DATA_CACHE.get(key)
    if cached is not None:
        return cached

    # Look up variable name from engine helpers
    try:
        from pystata_x.sfi._engine import _read_var_name_x86
        name = _read_var_name_x86(varno)
    except Exception:
        name = None

    if not name:
        _NUMERIC_DATA_CACHE[key] = 0.0
        return 0.0

    cmd = f"display {name}[{obs + 1}]"
    out = _exec(cmd)
    if out is None:
        _NUMERIC_DATA_CACHE[key] = 0.0
        return 0.0

    try:
        val = float(out)
        _NUMERIC_DATA_CACHE[key] = val
        return val
    except (ValueError, TypeError):
        _NUMERIC_DATA_CACHE[key] = 0.0
        return 0.0


# ─── String data cell ──────────────────────────────────────────────────


_STRING_DATA_CACHE: dict[tuple[int, int], str] = {}


def read_string(varno: int, obs: int) -> Optional[str]:
    """Read a string cell via ``display <varname>[<obs+1>]``."""
    key = (varno, obs)
    cached = _STRING_DATA_CACHE.get(key)
    if cached is not None:
        return cached

    try:
        from pystata_x.sfi._engine import _read_var_name_x86
        name = _read_var_name_x86(varno)
    except Exception:
        name = None

    if not name:
        _STRING_DATA_CACHE[key] = ""
        return ""

    cmd = f'display {name}[{obs + 1}]'
    out = _exec(cmd)
    if out is None:
        _STRING_DATA_CACHE[key] = ""
        return ""
    # Stata wraps the value in backtick quotes for string display:
    #   `hello world'
    # Strip them if present.
    if out.startswith("`") and out.endswith("'"):
        out = out[1:-1]
    _STRING_DATA_CACHE[key] = out
    return out


# ─── Numeric scalar ────────────────────────────────────────────────────


_NUMERIC_SCALAR_CACHE: dict[str, float] = {}


def read_scalar(name: str) -> float:
    """Read a numeric scalar via ``display``.

    ``c()``-style system values use ``display c(<name>)``;
    regular scalars use ``display scalar(<name>)``.
    """
    cached = _NUMERIC_SCALAR_CACHE.get(name)
    if cached is not None:
        return cached

    if name.startswith("c(") or name.startswith("c_"):
        inner = name[2:-1] if name.startswith("c(") else name[2:]
        cmd = f"display c({inner})"
    else:
        cmd = f"display scalar({name})"
    out = _exec(cmd)
    if out is None:
        _NUMERIC_SCALAR_CACHE[name] = 0.0
        return 0.0

    try:
        val = float(out)
        _NUMERIC_SCALAR_CACHE[name] = val
        return val
    except (ValueError, TypeError):
        _NUMERIC_SCALAR_CACHE[name] = 0.0
        return 0.0


# ─── String scalar ─────────────────────────────────────────────────────


_STRING_SCALAR_CACHE: dict[str, str] = {}


def read_string_scalar(name: str) -> Optional[str]:
    """Read a system/string scalar via ``display``.

    ``c()``-style system values use ``display c(<name>)``;
    regular string scalars use ``display scalar(<name>)``.
    """
    cached = _STRING_SCALAR_CACHE.get(name)
    if cached is not None:
        return cached

    # c(...) values are system constants, not named scalars
    if name.startswith("c(") or name.startswith("c_"):
        inner = name[2:-1] if name.startswith("c(") else name[2:]
        cmd = f"display c({inner})"
    else:
        cmd = f"display scalar({name})"
    out = _exec(cmd)
    if out is None:
        _STRING_SCALAR_CACHE[name] = ""
        return ""
    if out.startswith("`") and out.endswith("'"):
        out = out[1:-1]
    _STRING_SCALAR_CACHE[name] = out
    return out


# ─── Macro ─────────────────────────────────────────────────────────────


_MACRO_CACHE: dict[str, str] = {}


def get_macro(name: str) -> str:
    """Get a global macro via ``display "$<name>"``.

    ``c(...)`` names are system values, not macros, so we fall back
    to ``display c(...)`` for those.

    Returns ``""`` (empty string) when the value does not exist,
    matching the official SFI API contract.
    """
    cached = _MACRO_CACHE.get(name)
    if cached is not None:
        return cached

    # c() values are system constants, not global macros
    if name.startswith("c(") or name.startswith("c_"):
        inner = name[2:-1] if name.startswith("c(") else name[2:]
        cmd = f"display c({inner})"
    else:
        cmd = f'display "${name}"'
    out = _exec(cmd)
    if out is None:
        _MACRO_CACHE[name] = ""
        return ""
    _MACRO_CACHE[name] = out
    return out


def set_macro(name: str, value: str) -> bool:
    """Set a global macro via ``global <name> <value>``."""
    # Invalidate cache
    _MACRO_CACHE.pop(name, None)
    cmd = f"global {name} {value}"
    eng = _get_engine_lib()
    if eng is None:
        return False
    try:
        eng.StataSO_ClearOutputBuffer()
        rc = eng.StataSO_Execute(cmd.encode("utf-8", errors="replace"))
        return rc == 0
    except Exception:
        return False


def del_macro(name: str) -> bool:
    """Delete a global macro via ``macro drop <name>``."""
    _MACRO_CACHE.pop(name, None)
    cmd = f"macro drop {name}"
    eng = _get_engine_lib()
    if eng is None:
        return False
    try:
        eng.StataSO_ClearOutputBuffer()
        rc = eng.StataSO_Execute(cmd.encode("utf-8", errors="replace"))
        return rc == 0
    except Exception:
        return False


# ─── Cache control ─────────────────────────────────────────────────────


_MACRO_TEMP_ID = 0


def _next_tmp_macro() -> str:
    """Return a unique temporary macro name."""
    global _MACRO_TEMP_ID
    _MACRO_TEMP_ID += 1
    return f"__px_x86_tmp_{_MACRO_TEMP_ID}"


def read_var_value_label(varno: int) -> str:
    """Get the value-label name attached to a Stata variable.

    Uses Stata's ``: value label <varname>`` extended macro function
    via compound-quoted display.
    """
    import pystata_x.sfi._engine as eng_mod
    tbl_name = eng_mod._read_var_name_x86(varno)
    if not tbl_name:
        return ""
    eng = _get_engine_lib()
    if eng is None:
        return ""
    try:
        # Set local from extended function, then display with compound quoting
        eng.StataSO_Execute(f"local __vvlbl : value label {tbl_name}".encode())
        eng.StataSO_ClearOutputBuffer()
        # di `\"`__vvlbl'\"'  -- compound backtick quoting
        cmd = (
            b"di `\"`__vvlbl'\"'"
        )
        rc = eng.StataSO_Execute(cmd)
        if rc != 0:
            return ""
        buf = eng.StataSO_GetOutputBuffer
        buf.restype = ctypes.c_char_p
        out = buf().decode()
        for line in out.split("\n"):
            s = line.strip()
            if s and not s.startswith(".") and not s.startswith("r("):
                return s
        return ""
    except Exception:
        return ""


def read_value_label_names() -> list:
    """List all value-label names via ``label dir``."""
    lines = _exec_all("label dir")
    if not lines:
        return []
    names = []
    for line in lines:
        s = line.strip().strip('"')
        if s:
            names.append(s)
    return names


def read_value_label(name: str) -> list:
    """Get the label texts for a value-label set via ``label list <name>``.

    Returns a list of label strings (parallel to values returned by read_value_label_values).
    """
    lines = _exec_all(f"label list {name}")
    if not lines:
        return []
    labels: list = []
    for line in lines:
        s = line.strip()
        if s and not s.startswith(f"{name}:"):
            parts = s.split(None, 1)
            if len(parts) == 2:
                labels.append(parts[1])
    return labels


def read_value_label_values(name: str) -> list:
    """Get the integer values for a value-label set.

    Returns a list of int values (parallel to labels returned by read_value_label).
    """
    lines = _exec_all(f"label list {name}")
    if not lines:
        return []
    vals: list = []
    for line in lines:
        s = line.strip()
        if s and not s.startswith(f"{name}:"):
            parts = s.split(None, 1)
            if len(parts) == 2:
                try:
                    vals.append(int(parts[0]))
                except ValueError:
                    pass
    return vals


def read_value_label_exists(name: str) -> bool:
    """Check if a value label exists."""
    lines = _exec_all(f"label list {name}")
    if not lines:
        return False
    for line in lines:
        s = line.strip()
        if s.startswith(f"{name}:"):
            return True
    return False


def store_double(varno: int, obs: int, value: float) -> bool:
    """Write a numeric cell via ``replace <varname>[<obs>] = <value>``.

    Uses an intermediate global macro to safely transport the float value
    through StataSO_Execute.
    """
    import pystata_x.sfi._engine as eng_mod
    tbl_name = eng_mod._read_var_name_x86(varno)
    if not tbl_name:
        return False
    eng = _get_engine_lib()
    if eng is None:
        return False
    tmp = _next_tmp_macro()
    try:
        eng.StataSO_Execute(f"global {tmp} {value}".encode())
        eng.StataSO_ClearOutputBuffer()
        rc = eng.StataSO_Execute(
            f"replace {tbl_name} = ${tmp} in {obs + 1}".encode()
        )
        eng.StataSO_Execute(f"macro drop {tmp}".encode())
        return rc == 0
    except Exception:
        return False


def store_string(varno: int, obs: int, value: str) -> bool:
    """Write a string cell via ``replace <varname>[<obs>] = "<value>"``."""
    import pystata_x.sfi._engine as eng_mod
    tbl_name = eng_mod._read_var_name_x86(varno)
    if not tbl_name:
        return False
    eng = _get_engine_lib()
    if eng is None:
        return False
    try:
        eng.StataSO_ClearOutputBuffer()
        rc = eng.StataSO_Execute(
            f'replace {tbl_name} = "{value}" in {obs + 1}'.encode("utf-8", errors="replace")
        )
        return rc == 0
    except Exception:
        return False


# ─── Older cache control (keep for backwards compat) ────────────────────


def clear_cache() -> None:
    """Clear all cached values (call after dataset changes)."""
    _NUMERIC_DATA_CACHE.clear()
    _STRING_DATA_CACHE.clear()
    _NUMERIC_SCALAR_CACHE.clear()
    _STRING_SCALAR_CACHE.clear()
    _MACRO_CACHE.clear()
