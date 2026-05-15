"""Unit tests for ``pystata_x._config``.

Tests the config module's API surface and state management without
loading the actual Stata shared library.
"""

from __future__ import annotations

import pytest


class TestCheckInitialized:
    """check_initialized() must raise SystemError when uninitialised."""

    def test_raises_when_not_initialized(self):
        from pystata_x._config import check_initialized
        import pystata_x._config as cfg
        saved = cfg.stinitialized
        cfg.stinitialized = False
        try:
            with pytest.raises(SystemError, match="not been initialised"):
                check_initialized()
        finally:
            cfg.stinitialized = saved

    def test_noop_when_initialized(self):
        from pystata_x._config import check_initialized
        import pystata_x._config as cfg
        saved = cfg.stinitialized
        cfg.stinitialized = True
        try:
            check_initialized()  # should not raise
        finally:
            cfg.stinitialized = saved


class TestStatus:
    """status() should print current state without errors."""

    def test_status_prints_when_initialized(self, capsys):
        from pystata_x._config import status
        import pystata_x._config as cfg
        saved = cfg.stinitialized
        cfg.stinitialized = True
        try:
            status()
            captured = capsys.readouterr()
            assert "Stata version" in captured.out
        finally:
            cfg.stinitialized = saved

    def test_status_not_initialized(self, capsys):
        from pystata_x._config import status
        import pystata_x._config as cfg
        saved = cfg.stinitialized
        cfg.stinitialized = False
        try:
            status()
            captured = capsys.readouterr()
            assert "not been initialised" in captured.out
        finally:
            cfg.stinitialized = saved


class TestIsStataInitialized:
    """is_stata_initialized() reflects the module state."""

    def test_true_when_initialized(self):
        from pystata_x._config import is_stata_initialized
        import pystata_x._config as cfg
        saved = cfg.stinitialized
        cfg.stinitialized = True
        try:
            assert is_stata_initialized() is True
        finally:
            cfg.stinitialized = saved

    def test_false_when_not(self):
        from pystata_x._config import is_stata_initialized
        import pystata_x._config as cfg
        saved = cfg.stinitialized
        cfg.stinitialized = False
        try:
            assert is_stata_initialized() is False
        finally:
            cfg.stinitialized = saved


class TestSetStreamingOutput:
    """set_streaming_output() updates stconfig."""

    def test_enable(self):
        from pystata_x._config import set_streaming_output, stconfig
        set_streaming_output(True)
        assert stconfig["streamout"] == "on"

    def test_disable(self):
        from pystata_x._config import set_streaming_output, stconfig
        set_streaming_output(False)
        assert stconfig["streamout"] == "off"


class TestEncodeDecode:
    """Internal encode/decode helpers."""

    def test_encode(self):
        from pystata_x._config import _encode
        assert _encode("hello") == b"hello"
        assert _encode("") == b""

    def test_decode(self):
        from pystata_x._config import _decode
        assert _decode(b"hello") == "hello"
        assert _decode(None) == ""

    def test_decode_with_errors(self):
        from pystata_x._config import _decode
        # Invalid UTF-8 should not crash
        result = _decode(b"\xff\xfe\x00\x01")
        assert isinstance(result, str)
