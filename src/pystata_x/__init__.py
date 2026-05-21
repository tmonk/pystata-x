"""pystata-x: Independent drop-in replacement for StataCorp's pystata.

Fast Stata-Python bridge for headless / AI-agent use cases.

Key entry points
----------------
run(code, ...)     — Execute Stata commands (vendor-compatible, returns None)
execute(code, ...) — Execute Stata commands (fast, returns (output, rc) tuple)
config             — Config module (init, status, settings)
statasetup.config()— One-shot Stata initialisation (drop-in for ``stata_setup``)
"""

# SPDX-FileCopyrightText: 2025 Thomas Monk <t.d.monk@lse.ac.uk>
# SPDX-License-Identifier: AGPL-3.0-only

from __future__ import annotations

from pystata_x._core import run, execute, get_output, ExecuteResult
from pystata_x import _config as config

__author__ = "Thomas Monk"


def __getattr__(name: str):
    """Lazy import of importlib.metadata for ``__version__``.

    ``importlib.metadata`` is expensive to import (~30 ms). We defer
    it until someone actually accesses ``pystata_x.__version__``,
    which is almost never needed during cold-start initialisation.
    """
    if name == "__version__":
        try:
            from importlib.metadata import version as _v
            return _v("pystata-x")
        except Exception:
            return "0.0.0.dev0"
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__: list[str] = []
