"""Benchmark pystata vs pystata-x command execution.

Uses subprocess-per-group to measure Stata command execution speed.
Each subprocess initializes Stata once, then loops over the benchmark
function many times, reporting mean-per-call timing.
"""

# SPDX-FileCopyrightText: 2025 Thomas Monk <t.d.monk@lse.ac.uk>
# SPDX-License-Identifier: AGPL-3.0-only

from __future__ import annotations

import pathlib
import sys

import pytest

from .conftest import subprocess_benchmark, STATA_ROOT, STATA_EDITION

_REPO_SRC = str(pathlib.Path(__file__).resolve().parent.parent / "src")

PYSTATA_SETUP = f"""\
import sys
sys.path.insert(0, "{STATA_ROOT}/utilities")
import stata_setup
stata_setup.config("{STATA_ROOT}", "{STATA_EDITION}", splash=False)
"""

# Our optimised setup: init Stata using pystata (it needs the shared lib),
# then our _core.run wraps it with faster buffer handling.
FAST_SETUP = f"""\
import sys
sys.path.insert(0, "{_REPO_SRC}")
sys.path.insert(0, "{STATA_ROOT}/utilities")
import stata_setup
stata_setup.config("{STATA_ROOT}", "{STATA_EDITION}", splash=False)
from src.pystata_x._core import run as fast_run
"""


# ======================================================================
# 1. Simple command: display 1+1
# ======================================================================

class TestSimpleCommand:
    """Measure overhead of executing a trivial Stata command."""

    @pytest.mark.benchmark(min_rounds=1, warmup=False)
    def test_pystata_quietly(self, benchmark):
        result = subprocess_benchmark(
            PYSTATA_SETUP,
            'from pystata.stata import run as r; r("display 1+1", quietly=True)',
            "pystata.stata.run (quietly)", benchmark, min_time=1.0,
        )
        assert result is not None

    @pytest.mark.benchmark(min_rounds=1, warmup=False)
    def test_pystata_direct_sdk(self, benchmark):
        """Direct StataSO_Execute call."""
        result = subprocess_benchmark(
            PYSTATA_SETUP,
            """\
from pystata import config
e = config.stlib.StataSO_Execute
en = config.get_encode_str
go = config.get_output
config.stlib.StataSO_ClearOutputBuffer()
rc = e(en("display 1+1"), False)
out = go() or ""
""",
            "direct StataSO_Execute", benchmark, min_time=1.0,
        )
        assert result is not None

    @pytest.mark.benchmark(min_rounds=1, warmup=False)
    def test_fast_run_simple(self, benchmark):
        result = subprocess_benchmark(
            FAST_SETUP,
            'fast_run("display 1+1")',
            "pystata-x.run (simple)", benchmark, min_time=1.0,
        )
        assert result is not None

    @pytest.mark.benchmark(min_rounds=1, warmup=False)
    def test_fast_run_quietly(self, benchmark):
        result = subprocess_benchmark(
            FAST_SETUP,
            'fast_run("display 1+1", quietly=True)',
            "pystata-x.run (quietly)", benchmark, min_time=1.0,
        )
        assert result is not None

    @pytest.mark.benchmark(min_rounds=1, warmup=False)
    def test_fast_run_nocapture(self, benchmark):
        result = subprocess_benchmark(
            FAST_SETUP,
            'fast_run("display 1+1", quietly=True, capture=False)',
            "pystata-x.run (no capture)", benchmark, min_time=1.0,
        )
        assert result is not None


# ======================================================================
# 2. Multi-line command
# ======================================================================

_MULTILINE_CODE = """\
sysuse auto, clear
regress price mpg weight
predict pred
summarize pred
"""

class TestMultiLine:
    """Measure overhead of multi-line command execution (temp do-file)."""

    @pytest.mark.benchmark(min_rounds=1, warmup=False)
    def test_pystata_multiline(self, benchmark):
        result = subprocess_benchmark(
            PYSTATA_SETUP,
            f'from pystata.stata import run as r; r("""{_MULTILINE_CODE}""", quietly=True)',
            "pystata.stata.run (multiline)", benchmark, min_time=2.0,
        )
        assert result is not None

    @pytest.mark.benchmark(min_rounds=1, warmup=False)
    def test_fast_multiline(self, benchmark):
        result = subprocess_benchmark(
            FAST_SETUP,
            f'fast_run("""{_MULTILINE_CODE}""")',
            "pystata-x.run (multiline)", benchmark, min_time=2.0,
        )
        assert result is not None


# ======================================================================
# 3. Command with echo
# ======================================================================

class TestWithEcho:
    """Measure overhead with echo enabled."""

    @pytest.mark.benchmark(min_rounds=1, warmup=False)
    def test_pystata_echo(self, benchmark):
        result = subprocess_benchmark(
            PYSTATA_SETUP,
            'from pystata.stata import run as r; r("display 1+1", echo=True)',
            "pystata.stata.run (echo=True)", benchmark, min_time=1.0,
        )
        assert result is not None

    @pytest.mark.benchmark(min_rounds=1, warmup=False)
    def test_fast_echo(self, benchmark):
        result = subprocess_benchmark(
            FAST_SETUP,
            'fast_run("display 1+1", echo=True)',
            "pystata-x.run (echo=True)", benchmark, min_time=1.0,
        )
        assert result is not None


# ======================================================================
# 4. get_output() overhead
# ======================================================================

class TestGetOutput:
    """Measure output buffer drain overhead."""

    @pytest.mark.benchmark(min_rounds=1, warmup=False)
    def test_pystata_get_output(self, benchmark):
        result = subprocess_benchmark(
            PYSTATA_SETUP,
            """\
from pystata import config
config.stlib.StataSO_Execute(config.get_encode_str('display "x"'), False)
out = config.get_output()
""",
            "pystata config.get_output()", benchmark, min_time=1.0,
        )
        assert result is not None

    @pytest.mark.benchmark(min_rounds=1, warmup=False)
    def test_fast_get_output(self, benchmark):
        result = subprocess_benchmark(
            FAST_SETUP,
            """\
from src.pystata_x import _config as fc
fc.stlib.StataSO_Execute(fc._encode('display "x"'), False)
out = fc.get_output()
""",
            "pystata-x config.get_output()", benchmark, min_time=1.0,
        )
        assert result is not None
