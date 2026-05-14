"""Independent drop-in replacement for the ``stata-setup`` PyPI package.

API compatible with ``stata_setup.config(path, edition, splash=True)``.
Internally uses ``pystata_x._config``.

Usage
-----
::

    from pystata_x.stata_setup import config
    config("/Applications/StataMP", "mp", splash=False)
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

    # Ensure utilities/ is on sys.path so that Stata-proprietary modules
    # (e.g. ``sfi``) are importable.
    utils_path = os.path.join(path, "utilities")
    if utils_path not in sys.path:
        sys.path.insert(0, utils_path)

    # Use our optimised initialiser
    from pystata_x import _config as fast_config

    fast_config.init(edition, st_path=path, splash=splash)
