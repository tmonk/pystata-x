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
from typing import Any

from pystata_x import _config as config

# Persistent temp-do-file path (resolved lazily to avoid tempfile import
# during cold startup).
_STATA_TEMP_DO: str | None = None
_STATA_TEMP_FD: int | None = None

# Pre-encoded byte strings — avoid encode() on every call (~64 ns/string).
_SHOWCOMMAND_OFF = b"set showcommand off"
_SHOWCOMMAND_ON = b"set showcommand on"
_GRAPH_DIR_QUERY = b"quietly graph dir, memory"
_STATA_TEMP_DO_BYTES: bytes | None = None  # resolved lazily
_INCLUDE_CMD_PREFIX = b'include "'
_INCLUDE_CMD_SUFFIX = b'"'

# Cached showcommand state — avoid toggling when the current state already
# matches the requested state.  Stata starts with showcommand on.
_SHOWCOMMAND_IS_ON: bool = True


# ---------- helpers ----------


def _set_showcommand(state_on: bool) -> None:
    """Toggle showcommand only if *state_on* differs from the cached state.

    Does nothing when the current state already matches the requested
    state (saves ~16 us on consecutive calls with the same echo setting).
    """
    global _SHOWCOMMAND_IS_ON
    if state_on == _SHOWCOMMAND_IS_ON:
        return
    cmd = _SHOWCOMMAND_ON if state_on else _SHOWCOMMAND_OFF
    config.stlib.StataSO_Execute(cmd, 0)
    _SHOWCOMMAND_IS_ON = state_on


def _get_include_cmd_bytes() -> bytes:
    """Return the pre-encoded include command for the temp do-file."""
    global _STATA_TEMP_DO_BYTES
    if _STATA_TEMP_DO_BYTES is None:
        _STATA_TEMP_DO_BYTES = _get_temp_do_path().encode("utf-8")
    return _INCLUDE_CMD_PREFIX + _STATA_TEMP_DO_BYTES + _INCLUDE_CMD_SUFFIX


def _get_temp_do_path() -> str:
    """Return the temp-do-file path, computing it on first use."""
    global _STATA_TEMP_DO
    if _STATA_TEMP_DO is None:
        import tempfile as _tempfile
        _STATA_TEMP_DO = os.path.join(_tempfile.gettempdir(), "_pystata_x_temp.do")
    return _STATA_TEMP_DO


def _ensure_temp_fd() -> int:
    """Return the pre-opened file descriptor for the temp do-file."""
    global _STATA_TEMP_FD
    if _STATA_TEMP_FD is None:
        _STATA_TEMP_FD = os.open(
            _get_temp_do_path(),
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644
        )
    return _STATA_TEMP_FD


def _write_temp_do(code: str, suffix: bytes = b"") -> None:
    """Overwrite the temp do-file with *code* [+ *suffix*] using the cached fd.

    Uses ftruncate + lseek + write to avoid the overhead of repeated
    open()/close() syscalls (9 µs vs 49 µs on macOS).  When *suffix*
    is provided it is written immediately after *code* (avoids an extra
    Python string concatenation for bundled graph queries).
    """
    fd = _ensure_temp_fd()
    bdata = code.encode("utf-8")
    if suffix:
        # Add a newline separator between the user code and the suffix
        bdata = bdata + b"\n" + suffix
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

    Returns a list of graph names, or None if tracking is unavailable.
    """
    # x86_64: graph tracking not available without output buffer
    import sys, platform
    if sys.platform in ("linux", "linux2") and platform.machine() in ("x86_64", "amd64"):
        return None
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
    raw: bool = False,
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
    * **Graph tracking + single-line + echo=False** (NEW): also bundled via
      the temp-file path, **avoiding a costly second StataSO round-trip**.
      For ``echo=True`` it falls back to a separate graph dir call to
      preserve output content.

    ``set showcommand`` is toggled via a cached helper — no-ops when
    the current state already matches the requested state.  The ``echo``
    parameter on ``StataSO_Execute`` only affects the top-level command,
    not lines inside a do-file.

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
        If True, query in-memory graph state after execution.  The query
        is bundled into the do-file for multi-line code and for
        single-line code where ``echo=False`` — no extra StataSO call.
        Only single-line + ``echo=True`` uses a separate graph dir call.

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

    # Single-line + track_graphs + echo=False also routes through the
    # temp-file path so the graph dir query can be bundled, avoiding a
    # separate costly StataSO_Execute round-trip (~88 us).
    has_newline = "\n" in code
    need_tempfile = has_newline or quietly or (track_graphs and not echo)

    if need_tempfile:
        # ---- Temp-do-file path ----
        # StataSO_Execute cannot accept newlines, so multi-statement code
        # must be written to a temp do-file and include-d.
        #
        # When track_graphs=True, append the graph dir query directly into
        # the do-file, eliminating a separate StataSO round-trip.
        suffix = _GRAPH_DIR_QUERY if track_graphs else b""
        _write_temp_do(code, suffix)

        # Use cached showcommand state to avoid redundant toggling.
        # StataSO_Execute's echo param only controls the top-level command
        # (include).  Commands inside the do-file are controlled by
        # Stata's showcommand setting, so we must ensure it matches.
        #
        # We do NOT restore after the include — the next call will
        # toggle only if the requested state differs from the current
        # cached state.  This saves ~16 us on consecutive calls with
        # the same echo setting.
        _set_showcommand(not not echo)  # True=showcommand on, False=off

        stlib.StataSO_ClearOutputBuffer()

        # Build the include command from pre-encoded bytes.
        include_cmd = _get_include_cmd_bytes()
        if quietly:
            include_cmd = encode("qui ") + include_cmd

        rc = stlib.StataSO_Execute(include_cmd, False)

        output = get_output() if capture else ""

        # Bundled graph names (no extra StataSO round-trip)
        graph_names = _read_graph_names() if track_graphs else None

    else:
        # ---- Single-line fast path ----
        cmd = code.strip() if has_newline else code
        if quietly:
            cmd = "qui " + cmd

        stlib.StataSO_ClearOutputBuffer()
        rc = stlib.StataSO_Execute(encode(cmd), echo)
        output = get_output() if capture else ""

        # Single-line + track_graphs + echo=True: cannot bundle via
        # temp-file because that would change output content.  A
        # separate graph dir query is the only option.
        graph_names = None
        if track_graphs:
            stlib.StataSO_Execute(_GRAPH_DIR_QUERY, 0)
            graph_names = _read_graph_names()

    return ExecuteResult(output if raw else output.strip(), rc, graph_names)


def run(
    cmd: str,
    quietly: bool = False,
    echo: bool | None = None,
    inline: bool | None = None,
) -> None:
    """Execute Stata code and print output to stdout.

    Thin API-compatible wrapper around :func:`execute`.  Accepts the same
    parameters as StataCorp's ``pystata.stata.run()`` but performs **no**
    type validation, no empty-cmd short-circuit, no initialization check,
    and no comment detection of its own — all execution is delegated to
    the optimised :func:`execute` pipeline.

    Raises ``SystemError`` when Stata returns a non-zero return code
    (matching the vendor's observable error behaviour).

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
        Retained for API compatibility (no-op in headless mode;
        graphs are tracked via :func:`execute`\'s ``track_graphs``).

    Raises
    ------
    SystemError
        If Stata has not been initialised yet, or if Stata returns a
        non-zero return code.
    """
    result = execute(cmd, quietly=quietly, echo=echo, capture=True, raw=True)
    if result.output:
        print(result.output)
    if result.rc != 0:
        raise SystemError(result.output or "failed to execute the specified command")


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
