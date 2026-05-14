"""Independent Stata command execution.

Streamlined execution path that replaces StataCorp's ``pystata.stata``:

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

from pystata_x import _config as config

_STATA_TEMP_DO = os.path.join(tempfile.gettempdir(), "_pystata_x_temp.do")


# ---------------------------------------------------------------------------
# Auto-detect which Stata runtime to use
# ---------------------------------------------------------------------------

def _resolve_runtime():
    """Return (stlib, encode_func, get_output_func) from our runtime."""
    if config.stinitialized:
        return config.stlib, config._encode, config.get_output

    config.check_initialized()  # will raise
    return None, None, None  # unreachable


# ---------------------------------------------------------------------------
# Core execution
# ---------------------------------------------------------------------------


class ExecuteResult(tuple):
    """Result of a Stata command execution.

    Backward-compatible: can be unpacked as ``output, rc = result``
    because it is a 2-tuple with ``graph_names`` stored as an extra
    attribute.

    Fields
    ------
    output : str
        The captured Stata output text.
    rc : int
        Stata return code (0 = success).
    graph_names : list[str] | None
        List of graph names in memory after execution, or None if graph
        tracking was not requested.
    """

    def __new__(cls, output: str = "", rc: int = 0,
                graph_names: list[str] | None = None):
        obj = tuple.__new__(cls, (output, rc))
        obj._graph_names = graph_names
        return obj

    @property
    def output(self) -> str:
        return self[0]

    @property
    def rc(self) -> int:
        return self[1]

    @property
    def graph_names(self) -> list[str] | None:
        return self._graph_names


def _read_graph_names() -> list[str] | None:
    """Read in-memory graph list from Stata's ``r(list)`` via SFI Macro.

    Must be called **immediately after** a ``quietly graph dir, memory``
    was executed.  No separate StataSO round-trip needed.

    Returns a list of graph names, or None if SFI is unavailable.
    """
    try:
        from sfi import Macro
        raw = Macro.getGlobal("r(list)")
        if raw and raw.strip():
            return raw.split()
        return []
    except ImportError:
        return None


def execute(
    code: str,
    *,
    quietly: bool = False,
    echo: bool | None = None,
    capture: bool = True,
) -> tuple[str, int]:
    """Execute Stata code and return ``(output_text, return_code)``.

    This is the fast internal execution function, designed for programmatic
    use by headless / AI-agent callers (e.g. ``stata-agent``).

    Parameters
    ----------
    code : str
        One or more Stata commands.  Multi-line blocks are written to a
        temporary do-file and executed via ``include``.
    quietly : bool
        If True, prepend ``qui`` to single-line commands (suppress output).
    echo : bool or None
        Whether to echo the command in output.  ``None`` = use global default
        (``config.stconfig.get("cmdshow", "default")``).
    capture : bool
        If False, skip output buffer drain (useful for internal
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

    # Fast path: single-line command -> StataSO_Execute directly
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


def run(
    cmd: str,
    quietly: bool = False,
    echo: bool | None = None,
    inline: bool | None = None,
) -> None:
    """Execute Stata code with the original ``pystata.stata.run()`` API.

    This is a drop-in replacement for StataCorp's ``pystata.stata.run()``.
    Unlike :func:`execute`, this function **prints output to stdout** and
    **raises ``SystemError``** when Stata returns a non-zero return code.

    Parameters
    ----------
    cmd : str
        The Stata command(s) to execute.
    quietly : bool
        Suppress output from Stata commands.  Default ``False``.
    echo : bool or None
        Whether to echo the command in the output.  ``None`` = use the
        global setting (``config.stconfig["cmdshow"]``).
    inline : bool or None
        Whether to display graphs inline.  ``None`` = use the global
        setting (``config.stconfig["grshow"]``).  In headless/CLI mode
        this is effectively a no-op unless a Jupyter kernel is active.

    Raises
    ------
    SystemError
        If Stata returns a non-zero return code.
    """
    output, rc = execute(cmd, quietly=quietly, echo=echo, capture=True)

    if output:
        print(output)

    if rc != 0:
        raise SystemError(output or f"Stata command failed with return code {rc}")


def get_output() -> str:
    """Drain the Stata output buffer and return its contents."""
    return config.get_output()


def get_stata_error() -> str | None:
    """Check if the last operation produced an error indicator in the buffer.

    Returns the error text if found, or None if no obvious error or if the
    ``sfi`` module is not available.
    """
    try:
        import sfi  # noqa: F811
        rc = sfi.Scalar.getValue("c(rc)")
        if rc is not None and int(rc) != 0:
            return f"Stata return code: {rc}"
    except Exception:
        pass
    return None
