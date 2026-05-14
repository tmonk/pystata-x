"""Optimised drop-in replacement for the ``stata-setup`` PyPI package.

API compatible with ``stata_setup.config(path, edition, splash=True)``.
Internally uses ``src.stata_fast._config`` instead of pystata's original
``config.init()`` path.

Usage
-----
::

    import stata_setup
    stata_setup.config("/Applications/StataMP", "mp", splash=False)
    from pystata import stata  # now works normally
    stata.run("sysuse auto")
"""

# SPDX-FileCopyrightText: 2025 Thomas Monk <t.d.monk@lse.ac.uk>
# SPDX-License-Identifier: AGPL-3.0-only

from __future__ import annotations

import os
import sys
from typing import Any


def config(path: str, edition: str, splash: bool = True) -> None:
    """Configure and initialise Stata within Python.

    Parameters
    ----------
    path : str
        Stata's installation root directory (the folder that contains
        ``utilities/``).  On macOS this is typically
        ``/Applications/StataMP``, ``/Applications/StataSE``, etc.
    edition : str
        The Stata edition — one of ``"mp"``, ``"se"``, or ``"be"``.
    splash : bool
        Show the Stata splash banner on startup.  Default True.
    """
    if not os.path.isdir(path):
        raise OSError(f"Path does not exist: {path}")
    if not os.path.isdir(os.path.join(path, "utilities")):
        raise OSError(f"Not a Stata installation (missing utilities/): {path}")

    # If the original pystata package lives under utilities/, make it
    # importable so that existing code can ``from pystata import ...``.
    pystata_path = os.path.join(path, "utilities")
    if pystata_path not in sys.path:
        sys.path.insert(0, pystata_path)

    # Use our optimised initialiser
    from stata_fast import _config as fast_config

    fast_config.init(edition, st_path=path, splash=splash)

    # Sync our state back to pystata's config so that existing code
    # that imports ``pystata.config`` or ``pystata.stata`` works.
    import pystata.config as pystata_cfg
    pystata_cfg.stlib = fast_config.stlib
    pystata_cfg.sthome = fast_config.sthome
    pystata_cfg.stversion = fast_config.stversion
    pystata_cfg.stedition = fast_config.stedition
    pystata_cfg.stsplash = fast_config.stsplash
    pystata_cfg.stinitialized = True
    pystata_cfg.stlibpath = fast_config.stlibpath
    pystata_cfg.stconfig.update(fast_config.stconfig)

    # Make our optimised ``run`` available as ``pystata.stata.run``
    # so existing code can use it transparently.
    import pystata.stata as orig_stata
    from stata_fast._core import run as fast_run

    # Monkey-patch only if the caller hasn't explicitly opted in already
    orig_stata.run = fast_run
