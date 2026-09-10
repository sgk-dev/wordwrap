"""Unit tests for hotkey parsing and dispatch resolution (evdev backend)."""

from unittest.mock import patch

with patch("evdev.InputDevice"), patch("evdev.ecodes"):
    from sgk_wordwrap.input.evdev_backend import (
        _sgk_parse_hotkey,
        _sgk_pick_hotkey,
        _SgkHotkeySpec,
    )


class TestParseHotkey:
    def test_single_key(self):
        mods, key = _sgk_parse_hotkey("pause")
        assert mods == frozenset()
        assert key == "pause"

    def test_ctrl_f1(self):
        mods, key = _sgk_parse_hotkey("ctrl+f1")
        assert mods == frozenset({"ctrl"})
        assert key == "f1"

    def test_ctrl_shift_f1(self):
        mods, key = _sgk_parse_hotkey("ctrl+shift+f1")
        assert mods == frozenset({"ctrl", "shift"})
        assert key == "f1"

    def test_gnome_style_angle_brackets(self):
        mods, key = _sgk_parse_hotkey("<Ctrl>F1")
        assert mods == frozenset({"ctrl"})
        assert key == "f1"

    def test_gnome_style_primary(self):
        mods, key = _sgk_parse_hotkey("<Primary><Shift>F1")
        assert mods == frozenset({"ctrl", "shift"})
        assert key == "f1"


def _specs():
    return [
        _SgkHotkeySpec("convert", frozenset({"ctrl"}), "f1"),
        _SgkHotkeySpec("convert_terminal", frozenset({"ctrl", "shift"}), "f1"),
        _SgkHotkeySpec("toggle", frozenset({"ctrl"}), "pause"),
    ]


class TestPickHotkey:
    def test_exact_single_modifier(self):
        assert _sgk_pick_hotkey({"ctrl"}, "f1", _specs()) == "convert"

    def test_most_specific_wins(self):
        # Ctrl+Shift+F1 pressed: both 'convert' (ctrl) and 'convert_terminal'
        # (ctrl+shift) are satisfied — the more specific one must win.
        assert (
            _sgk_pick_hotkey({"ctrl", "shift"}, "f1", _specs())
            == "convert_terminal"
        )

    def test_different_trigger_key(self):
        assert _sgk_pick_hotkey({"ctrl"}, "pause", _specs()) == "toggle"

    def test_missing_modifier_no_match(self):
        assert _sgk_pick_hotkey(set(), "f1", _specs()) is None

    def test_extra_unrelated_modifier_still_matches_lenient(self):
        # Alt also held — we don't require an exact set, only that the spec's
        # modifiers are all present.
        assert _sgk_pick_hotkey({"ctrl", "alt"}, "f1", _specs()) == "convert"

    def test_unknown_key(self):
        assert _sgk_pick_hotkey({"ctrl"}, "z", _specs()) is None


class TestLoggingExtraKeysAreSafe:
    """Regression: `extra={"name": ...}` collides with LogRecord and kills the
    evdev listener thread. Reserved keys must never be used in extra=."""

    def test_reserved_key_raises_but_our_key_does_not(self):
        import logging

        import pytest

        rec_logger = logging.getLogger("sgk_test_reserved")
        rec_logger.setLevel(logging.DEBUG)
        rec_logger.addHandler(logging.NullHandler())
        with pytest.raises(KeyError):
            rec_logger.debug("x", extra={"name": "convert"})
        # the key the backend actually uses must be accepted
        rec_logger.debug("x", extra={"hotkey": "convert"})

    def test_backend_source_has_no_reserved_extra_keys(self):
        import pathlib

        import sgk_wordwrap.input.evdev_backend as mod

        src = pathlib.Path(mod.__file__).read_text()
        for reserved in ('extra={"name"', 'extra={"module"', 'extra={"process"'):
            assert reserved not in src

