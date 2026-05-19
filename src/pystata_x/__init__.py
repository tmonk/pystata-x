"""pystata-x: Independent drop-in replacement for StataCorp's pystata.

Fast Stata-Python bridge for headless / AI-agent use cases.

Key entry points
----------------
run(code, ...)     — Execute Stata commands (vendor-compatible, returns None)
execute(code, ...) — Execute Stata commands (fast, returns (output, rc) tuple)
config             — Config module (init, status, settings)
statasetup.config()— One-shot Stata initialisation (drop-in for ``stata_setup``)

Import optimisation
-------------------
All heavy submodules (`_core`, `sfi`, `_config`) are loaded lazily on first
use rather than eagerly at ``import pystata_x`` time.  This makes a bare
``from pystata_x.stata_setup import config`` cost ~2 ms instead of ~35 ms.
"""

# SPDX-FileCopyrightText: 2025 Thomas Monk <t.d.monk@lse.ac.uk>
# SPDX-License-Identifier: AGPL-3.0-only

from __future__ import annotations

import sys as _sys
from types import ModuleType as _ModuleType

__all__ = [
    "run", "execute", "get_output", "ExecuteResult", "config",
]

# Defer version import — importlib.metadata is heavy (~17 ms)
__version__: str = "0.0.0.dev0"


def _get_version() -> str:
    try:
        from importlib.metadata import version as _v
        return _v("pystata-x")
    except Exception:
        return "0.0.0.dev0"

__author__ = "Thomas Monk"


# ---------------------------------------------------------------------------
# Lazy imports – heavy submodules loaded on first attribute access
# ---------------------------------------------------------------------------
_LazyModules: dict[str, _ModuleType | object] = {}


def __getattr__(name: str):
    """Lazy-import heavy submodules on first attribute access (PEP 562)."""
    # Map of public attribute → (module, attribute_to_get)
    _LAZY_MAP: dict[str, tuple[str, str | None]] = {
        "run":        ("pystata_x._core", "run"),
        "execute":    ("pystata_x._core", "execute"),
        "get_output": ("pystata_x._core", "get_output"),
        "ExecuteResult": ("pystata_x._core", "ExecuteResult"),
        "config":     ("pystata_x._config", None),  # return module itself
    }

    if name in _LAZY_MAP:
        mod_name, attr = _LAZY_MAP[name]
        if mod_name not in _LazyModules:
            _import_module(mod_name)
        mod = _LazyModules[mod_name]
        return mod if attr is None else getattr(mod, attr)

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _import_module(mod_name: str) -> None:
    """Import *mod_name* and cache the result."""
    if mod_name in _LazyModules:
        return
    import importlib
    mod = importlib.import_module(mod_name)
    _LazyModules[mod_name] = mod


def __dir__() -> list[str]:
    return sorted(__all__ + ["__version__", "__author__", "__file__", "__name__",
                             "__doc__", "__package__", "__path__", "__spec__"])
