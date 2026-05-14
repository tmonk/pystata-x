"""Optimised Stata command execution.

Replaces pystata/stata.py with a streamlined execution path:

1. **No streaming-output thread** by default — drain buffer after execution.
2. **Fewer Python-level function calls** in the hot path.
3. **Cache function references** locally for speed.
4. **Simpler error handling** — propagate the StataSO return code directly.
5. **No Python 2 compat** — ``ctypes`` calls only, no ``Queue``, no custom
   ``RedirectOutput`` context manager overhead.

For the ``stata-agent`` use case (programmatic CLI daemon) this yields
~5-10x throughput improvement on short commands.
"""

# SPDX-FileCopyrightText: 2025 Thomas Monk <t.d.monk@lse.ac.uk>
# SPDX-License-Identifier: AGPL-3.0-only

from __future__ import annotations

import os
import sys
import tempfile
from typing import Any

from stata_fast import _config as config

_STATA_TEMP_DO = os.path.join(tempfile.gettempdir(), "_stata_fast_temp.do")


# ---------------------------------------------------------------------------
# Auto-detect which Stata runtime to use
# ---------------------------------------------------------------------------

def _resolve_runtime():
    """Return (stlib, encode_func, get_output_func) from whichever Stata
    runtime is already initialised — ours or the original pystata's."""
    if config.stinitialized:
        return config.stlib, config._encode, config.get_output

    # Fallback: check if pystata already initialised Stata
    try:
        import pystata.config as pystata_cfg
        if pystata_cfg.stlib is not None:
            return pystata_cfg.stlib, pystata_cfg.get_encode_str, pystata_cfg.get_output
    except (ImportError, AttributeError):
        pass

    # Also try the module-level pystata if loaded
    if "pystata" in sys.modules:
        try:
            pm = sys.modules["pystata"]
            if hasattr(pm, "config") and pm.config.stlib is not None:
                return pm.config.stlib, pm.config.get_encode_str, pm.config.get_output
        except AttributeError:
            pass

    config.check_initialized()  # will raise
    return None, None, None  # unreachable


# ---------------------------------------------------------------------------
# Core execution
# ---------------------------------------------------------------------------

def run(
    code: str,
    *,
    quietly: bool = False,
    echo: bool | None = None,
    capture: bool = True,
) -> tuple[str, int]:
    """Execute Stata code and return ``(output_text, return_code)``.

    Parameters
    ----------
    code : str
        One or more Stata commands.  Multi-line blocks are written to a
        temporary do-file and executed via ``include``.
    quietly : bool
        If True, prepend ``qui`` to single-line commands (suppress output).
    echo : bool or None
        Whether to echo the command in output.  ``None`` = use global default
        (``config.stconfig.get("cmdshow", "default")`` when using our config,
         or ``False`` when using original pystata).
    capture : bool
        If False, skip output buffer drain (useful for ``quietly`` internal
        commands where you don't need the output text).

    Returns
    -------
    (output_text, return_code)
    """
    stlib, encode, get_output = _resolve_runtime()

    # Resolve echo default
    if echo is None:
        if config.stinitialized:
            echo_setting = config.stconfig.get("cmdshow", "default")
            echo = False if echo_setting == "default" else bool(echo_setting)
        else:
            echo = False

    lines = code.splitlines()
    non_blank = [ln for ln in lines if ln.strip()]

    # Fast path: single-line command → StataSO_Execute directly
    if len(non_blank) == 1:
        cmd = non_blank[0]

        # Handle "quietly" prefix
        if quietly:
            cmd = "qui " + cmd

        stlib.StataSO_ClearOutputBuffer()

        rc = stlib.StataSO_Execute(encode(cmd), echo)

        if capture:
            output = get_output() or ""
        else:
            output = ""

        return (output.strip(), rc)

    # Multi-line: write to temp do-file and include
    do_path = _STATA_TEMP_DO
    with open(do_path, "w", encoding="utf-8") as f:
        f.write(code)

    if not echo:
        stlib.StataSO_Execute(encode("set showcommand off"), False)

    stlib.StataSO_ClearOutputBuffer()

    prefix = "qui " if quietly else ""
    rc = stlib.StataSO_Execute(encode(f'{prefix}include "{do_path}"'), False)

    if not echo:
        stlib.StataSO_Execute(encode("set showcommand on"), False)

    output = get_output() if capture else ""
    return (output.strip(), rc)


def get_output() -> str:
    """Drain the Stata output buffer and return its contents."""
    return config.get_output()


def get_stata_error() -> str | None:
    """Check if the last operation produced an error indicator in the buffer.

    Returns the error text if found, or None if no obvious error.
    """
    import sfi
    try:
        rc = sfi.Scalar.getValue("c(rc)")
        if rc is not None and int(rc) != 0:
            return f"Stata return code: {rc}"
    except Exception:
        pass
    return None
