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

# Persistent temp-do-file + pre-opened file descriptor.
# We keep the fd open and reuse it via ftruncate+lseek+write,
# which is ~5× faster than opening/closing the file per call
# (9 µs vs 49 µs on macOS).
_STATA_TEMP_DO = os.path.join(tempfile.gettempdir(), "_pystata_x_temp.do")
_STATA_TEMP_FD: int | None = None


def _ensure_temp_fd() -> int:
    """Return the pre-opened file descriptor for the temp do-file."""
    global _STATA_TEMP_FD
    if _STATA_TEMP_FD is None:
        _STATA_TEMP_FD = os.open(
            _STATA_TEMP_DO,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644
        )
    return _STATA_TEMP_FD


def _write_temp_do(code: str) -> None:
    """Overwrite the temp do-file with *code* using the cached fd.

    Uses ftruncate + lseek + write to avoid the overhead of repeated
    open()/close() syscalls.
    """
    fd = _ensure_temp_fd()
    bdata = code.encode("utf-8")
    os.ftruncate(fd, 0)
    os.lseek(fd, 0, os.SEEK_SET)
    os.write(fd, bdata)


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
    track_graphs: bool = False,
) -> ExecuteResult:
    """Execute Stata code and return result as an ``ExecuteResult``.

    Backward-compatible: callers that unpack to ``output, rc = execute(...)``
    will continue to work because ``ExecuteResult`` is a positional tuple.

    **Execution paths:**

    * **Single-line** (fast path): passed directly to ``StataSO_Execute``.
    * **Multi-line**: written to a temp do-file and ``include``-d (necessary
      because ``StataSO_Execute`` does not accept newlines).
    * **Graph tracking + multi-line**: the graph dir query is **bundled
      into the same do-file**, eliminating a separate StataSO round-trip.
    * **Graph tracking + single-line**: the graph dir query runs as a
      separate StataSO call after the user code (cannot bundle).

    ``set showcommand`` is toggled per-call inside the include path to
    control command echoing — the ``echo`` parameter on ``StataSO_Execute``
    only affects the top-level command, not lines inside a do-file.

    Parameters
    ----------
    code : str
        One or more Stata commands.
    quietly : bool
        If True, prepend ``qui`` to single-line commands (suppress output).
        For multi-line with quietly=True the code is written to a temp
        do-file and ``qui include``-d (rare path).
    echo : bool or None
        Whether to echo the command in output.  ``None`` = use global default
        (``config.stconfig.get("cmdshow", "default")``).
    capture : bool
        If False, skip output buffer drain (useful for internal
        commands where you don't need the output text).
    track_graphs : bool
        If True, query in-memory graph state after execution.  For
        multi-line code the query is bundled into the do-file (no extra
        StataSO call).  For single-line it runs as a separate call.

    Returns
    -------
    ExecuteResult
        Fields: output, rc, graph_names (None when track_graphs=False).
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
    is_multiline = len(non_blank) > 1

    if is_multiline or quietly:
        # ---- Temp-do-file path (multi-line or quietly=True) ----
        # StataSO_Execute cannot accept newlines in a single call, so
        # we write a temp do-file and "include" it.
        #
        # When track_graphs=True, the graph dir query is bundled into
        # the same do-file, saving one StataSO round-trip.
        if track_graphs:
            code = code + "\nquietly graph dir, memory"

        _write_temp_do(code)

        # showcommand toggling: StataSO_Execute's echo param only
        # controls the top-level command (include).  Commands inside
        # the do-file are controlled by Stata's showcommand setting.
        if not echo:
            stlib.StataSO_Execute(
                encode("set showcommand off"), False
            )

        stlib.StataSO_ClearOutputBuffer()

        prefix = "qui " if quietly else ""
        rc = stlib.StataSO_Execute(
            encode(f'{prefix}include "{_STATA_TEMP_DO}"'), False
        )

        if not echo:
            stlib.StataSO_Execute(
                encode("set showcommand on"), False
            )

        output = get_output() if capture else ""

        # Bundled graph names (no extra StataSO round-trip)
        graph_names: list[str] | None = None
        if track_graphs:
            graph_names = _read_graph_names()

    else:
        # ---- Single-line fast path ----
        cmd = non_blank[0]
        if quietly:
            cmd = "qui " + cmd

        stlib.StataSO_ClearOutputBuffer()
        rc = stlib.StataSO_Execute(encode(cmd), echo)
        output = get_output() if capture else ""

        # Single-line + track_graphs: separate query (can't bundle)
        graph_names = None
        if track_graphs:
            try:
                stlib.StataSO_Execute(
                    encode("quietly graph dir, memory"), 0
                )
                graph_names = _read_graph_names()
            except Exception:
                graph_names = None

    return ExecuteResult(output.strip(), rc, graph_names)


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
    result = execute(cmd, quietly=quietly, echo=echo, capture=True)

    if result.output:
        print(result.output)

    if result.rc != 0:
        raise SystemError(result.output or f"Stata command failed with return code {result.rc}")


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
