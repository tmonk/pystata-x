"""Independent Stata initialisation and configuration.

Replacement for StataCorp's pystata/config.py with no Python 2
compatibility code, no IPython/Jupyter auto-detection overhead, and
no redundant preference-file I/O during init.

Key improvements
----------------
- No IPython/Jupyter probe during init (saves ~100 ms)
- No preference-file I/O during init (unless explicitly requested)
- Simplified shared-library search
- Pure Python 3 (>=3.11)
"""

# SPDX-FileCopyrightText: 2025 Thomas Monk <t.d.monk@lse.ac.uk>
# SPDX-License-Identifier: AGPL-3.0-only

from __future__ import annotations

import atexit
import os
import sys
from ctypes import cdll, c_char_p, c_int, POINTER

# ---------------------------------------------------------------------------
# Module state
# ---------------------------------------------------------------------------

stlib: Any = None          # ctypes CDLL instance (the loaded libstata)
sthome: str = ""           # Stata installation root
stversion: str = ""        # Stata version string (set after init)
stedition: str = ""        # Normalised edition: "BE", "SE", or "MP"
stsplash: bool = True
stinitialized: bool = False
stlibpath: str | None = None

# Default settings (mirrors pystata.config.stconfig)
stconfig: dict[str, Any] = {
    "grwidth":    ["default", "in"],
    "grheight":   ["default", "in"],
    "grformat":   "svg",
    "grshow":     False,       # default off — we're headless
    "cmdshow":    "default",
    "streamout":  "off",       # default off — direct buffer drain is faster
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _encode(s: str) -> bytes:
    return s.encode("utf-8")


def _decode(b: bytes | None) -> str:
    if b is None:
        return ""
    try:
        return b.decode("utf-8", "backslashreplace")
    except Exception:
        return b.decode("utf-8", errors="replace")


def _find_lib(st_home: str, edition: str, os_system: str = "") -> str | None:
    """Locate the Stata shared library.  Returns absolute path or None."""
    import platform

    if not os_system:
        os_system = platform.system()
    if os_system == "Windows":
        lib_name = f"{edition}-64.dll"
        lib_path = os.path.join(st_home, lib_name)
        return lib_path if os.path.isfile(lib_path) else None

    if os_system == "Darwin":
        lib_name = f"libstata-{edition}.dylib"
        app_map = {"be": "StataBE.app", "se": "StataSE.app", "mp": "StataMP.app"}
        lib_path = os.path.join(st_home, app_map[edition], "Contents", "MacOS", lib_name)
        return lib_path if os.path.isfile(lib_path) else None

    # Linux
    lib_name = f"libstata-{edition}.so" if edition != "be" else "libstata.so"
    lib_paths = [
        os.path.join(st_home, lib_name),
        os.path.join(st_home, "..", "distn", "linux64", lib_name),
        os.path.join(st_home, "..", "distn", "linux.64p", lib_name),
        os.path.join(st_home, "..", "distn", "linux.64", lib_name),
    ]
    for p in lib_paths:
        np = os.path.normpath(p)
        if os.path.isfile(np):
            return np
    return None


def _get_st_home(from_file: str | None = None) -> str:
    """Auto-detect Stata home by walking up from a known path."""
    from pathlib import Path

    if from_file is None:
        from_file = os.path.normpath(os.path.abspath(__file__))

    d_util = Path(from_file).parent
    # Walk up looking for utilities/ directory
    for parent in [d_util] + list(d_util.parents):
        if parent.name.lower() == "utilities":
            return str(parent.parent)
        if (parent / "utilities").is_dir():
            # We're in pystata-x package tree — can't auto-detect.
            # User must call statasetup.config(path, ...) explicitly.
            break
    raise ValueError(
        "Cannot auto-detect Stata installation path. "
        "Use `stata_setup.config(stata_path, edition)` explicitly."
    )


def _get_executable_path() -> str:
    """Return the Python executable path for Stata to use as -pyexec."""
    return sys.executable


def _is_arm_arch() -> bool:
    """Return True when running on an ARM-family machine."""
    machine = platform.machine().lower()
    return machine.startswith("arm") or machine.startswith("aarch64")


def _init_stata(splash: bool) -> int:
    """Call StataSO_Main to bootstrap the Stata engine.

    Uses NO ``-pyexec`` flag — we access Stata data through direct
    ``_bist_*`` C function calls, not through Stata's embedded Python.
    """
    stlib.StataSO_Main.restype = c_int
    stlib.StataSO_Main.argtypes = (c_int, POINTER(c_char_p))

    if splash:
        args = [""]
    else:
        args = ["", "-q"]

    c_argv = (c_char_p * len(args))()
    for i, a in enumerate(args):
        c_argv[i] = _encode(a)

    return stlib.StataSO_Main(len(args), c_argv)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def init(
    edition: str,
    st_path: str | None = None,
    splash: bool = True,
    *,
    streamout: bool = False,
) -> None:
    """Initialise Stata inside the current Python process.

    Parameters
    ----------
    edition : str
        One of ``"be"``, ``"se"``, or ``"mp"``.
    st_path : str, optional
        Path to the Stata installation root (the directory containing
        ``utilities/``).  If omitted, auto-detected from the file tree
        (only works when running inside Stata's bundled Python).
    splash : bool
        Show/hide the Stata splash message on startup.
    streamout : bool
        Enable streaming output (legacy behaviour).  Off by default;
        direct buffer drain after execution is much faster.
    """
    global stinitialized, stlib, stlibpath, sthome, stedition, stsplash, stversion

    if stinitialized:
        return

    if not _is_arm_arch():
        raise NotImplementedError(
            "This upstream merge path supports only the ARM native runtime."
        )

    if st_path is None:
        st_path = _get_st_home()

    st_path = os.path.normpath(st_path)
    if not os.path.isdir(st_path):
        raise OSError(f"Stata home directory does not exist: {st_path}")
    if not os.path.isdir(os.path.join(st_path, "utilities")):
        raise OSError(f"Not a Stata installation (missing utilities/): {st_path}")

    edition = edition.lower()
    if edition not in ("be", "se", "mp"):
        raise ValueError("edition must be one of be, se, or mp")

    os.environ["SYSDIR_STATA"] = st_path

    lib_path = _find_lib(st_path, edition)
    if lib_path is None:
        raise FileNotFoundError(
            f"Cannot find Stata shared library for edition '{edition}' "
            f"under {st_path}"
        )

    stlibpath = lib_path
    stedition = {"be": "BE", "se": "SE", "mp": "MP"}[edition]

    try:
        stlib = cdll.LoadLibrary(lib_path)
    except Exception as exc:
        raise RuntimeError(f"Failed to load Stata shared library: {exc}")

    sthome = st_path
    stinitialized = True
    stsplash = splash

    # Set streaming mode
    stconfig["streamout"] = "on" if streamout else "off"

    # On macOS, work around KMP duplicate-lib issue for MP edition
    if edition == "mp":
        import platform as _platform
        if _platform.system() == "Darwin":
            os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "True")

    # Bootstrap the Stata engine immediately (StataSO_Main).
    # This is the single most expensive init step (~75-85 ms) but
    # ensures the first execute() / run() call is equally fast.
    rc = _init_stata(splash)
    msg = get_output()
    if rc < 0:
        if rc == -7100:
            print(msg, end="")
        else:
            raise RuntimeError(
                f"Stata engine bootstrap failed (rc={rc}):\n{msg}"
            )
    else:
        if msg:
            print(msg, end="")

    # Read Stata version
    try:
        import sfi  # type: ignore[import-untyped]
        stversion = str(sfi.Scalar.getValue("c(stata_version)"))
    except Exception:
        stversion = ""


def bootstrap_stata_engine() -> None:
    """Ensure the Stata C engine has been bootstrapped.

    This is a no-op after :func:`init` — the engine bootstrap is
    performed during ``init()`` so that the first ``execute()`` /
    ``run()`` call has no additional startup latency.
    """
    pass


def check_initialized() -> None:
    """Raise ``SystemError`` if Stata has not been initialised."""
    if not stinitialized:
        raise SystemError(
            "Stata environment has not been initialised yet.\n"
            "Call `stata_setup.config(path, edition)` first."
        )


@atexit.register
def shutdown() -> None:
    """Shut down the Stata engine at interpreter exit."""
    if not stinitialized:
        return
    try:
        stlib.StataSO_Shutdown.restype = None
        stlib.StataSO_Shutdown()
    except Exception:
        pass


def is_stata_initialized() -> bool:
    return stinitialized


def get_output() -> str:
    """Drain and return the Stata output buffer."""
    stlib.StataSO_GetOutputBuffer.restype = c_char_p
    raw = stlib.StataSO_GetOutputBuffer()
    return _decode(c_char_p(raw).value if raw else None)


# ---------------------------------------------------------------------------
# Settings (simplified)
# ---------------------------------------------------------------------------

def status() -> None:
    """Print current configuration status."""
    if not stinitialized:
        print("Stata environment has not been initialised yet")
        return
    print(f"    Stata version       {stversion or stedition}")
    print(f"    Library path        {stlibpath}")
    print(f"    Streaming output    {stconfig['streamout']}")
    print(f"    Graph show          {stconfig['grshow']}")
    print(f"    Graph format        {stconfig['grformat']}")


def set_streaming_output(enabled: bool) -> None:
    """Enable/disable streaming output during command execution.

    Streaming output shows Stata's output incrementally as it runs.
    Disabled by default because draining the buffer after execution is
    significantly faster (no polling thread).
    """
    stconfig["streamout"] = "on" if enabled else "off"
