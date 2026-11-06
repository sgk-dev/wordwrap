"""Unit tests for hotkey parsing and dispatch resolution (evdev backend)."""

from unittest.mock import patch

import pytest

with patch("evdev.InputDevice"), patch("evdev.ecodes"):
    from sgk_wordwrap.input.evdev_backend import (
        _sgk_parse_hotkey,
        _sgk_pick_hotkey,
        _SgkHotkeySpec,
        sgk_hotkey_is_valid,
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
        # (ctrl+shift) are satisfied - the more specific one must win.
        assert (
            _sgk_pick_hotkey({"ctrl", "shift"}, "f1", _specs())
            == "convert_terminal"
        )

    def test_different_trigger_key(self):
        assert _sgk_pick_hotkey({"ctrl"}, "pause", _specs()) == "toggle"

    def test_missing_modifier_no_match(self):
        assert _sgk_pick_hotkey(set(), "f1", _specs()) is None

    def test_extra_unrelated_modifier_still_matches_lenient(self):
        # Alt also held - we don't require an exact set, only that the spec's
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



class TestHotkeyIsValid:
    @pytest.mark.parametrize("hotkey", [
        "ctrl+f1", "ctrl+shift+f1", "ctrl+pause", "super+space", "<Primary><Shift>F1", "f9",
    ])
    def test_valid(self, hotkey):
        pytest.importorskip("evdev")
        assert sgk_hotkey_is_valid(hotkey)

    @pytest.mark.parametrize("hotkey", [
        "", "ctrl+alt", "ctrl", "alt", "shift+super", "ctrl+control", "hyper+f1", "ctrl+nosuchkey",
    ])
    def test_invalid(self, hotkey):
        pytest.importorskip("evdev")
        assert not sgk_hotkey_is_valid(hotkey)


class _Ev:
    def __init__(self, code: int, value: int) -> None:
        self.code = code
        self.value = value


class _FakeEvdev:
    class events:
        class KeyEvent:
            key_up, key_down, key_hold = 0, 1, 2

    class ecodes:
        EV_KEY = 1
        KEY_A = 30
        KEY_LEFTCTRL = 29
        KEY_RIGHTCTRL = 97
        KEY_LEFTSHIFT = 42
        KEY_RIGHTSHIFT = 54
        KEY_LEFTALT = 56
        KEY_RIGHTALT = 100
        KEY_LEFTMETA = 125
        KEY_RIGHTMETA = 126
        KEY_F1 = 59
        KEY_F2 = 60
        KEY_PAUSE = 119

    class _Key:
        def __init__(self, ev) -> None:
            self.scancode = ev.code
            self.keystate = ev.value

    @classmethod
    def categorize(cls, ev):
        return cls._Key(ev)


def _listener(fired: list[str]):
    from sgk_wordwrap.input.evdev_backend import SgkEvdevHotkeyListener

    lst = SgkEvdevHotkeyListener({
        "convert": "ctrl+f1",
        "convert_terminal": "ctrl+shift+f1",
        "toggle": "ctrl+pause",
    })
    lst._callback = fired.append
    mods, triggers = lst._sgk_build_code_maps(_FakeEvdev)
    lst._mod_code_to_name = mods

    def send(code: int, value: int) -> None:
        lst._sgk_handle_key_event(
            _FakeEvdev, _Ev(code, value), mods, triggers, lst._pressed_codes
        )

    return lst, send


K = _FakeEvdev.ecodes


class TestKeyEvents:
    def test_ctrl_f1_down_fires_convert(self) -> None:
        fired: list[str] = []
        _, send = _listener(fired)
        send(K.KEY_LEFTCTRL, 1)
        send(K.KEY_F1, 1)
        assert fired == ["convert"]

    def test_ctrl_shift_f1_fires_terminal_not_convert(self) -> None:
        fired: list[str] = []
        _, send = _listener(fired)
        send(K.KEY_LEFTCTRL, 1)
        send(K.KEY_LEFTSHIFT, 1)
        send(K.KEY_F1, 1)
        assert fired == ["convert_terminal"]

    def test_key_up_and_autorepeat_do_not_fire(self) -> None:
        fired: list[str] = []
        _, send = _listener(fired)
        send(K.KEY_LEFTCTRL, 1)
        send(K.KEY_F1, 2)
        send(K.KEY_F1, 0)
        assert fired == []

    def test_releasing_right_ctrl_keeps_left_ctrl_held(self) -> None:
        fired: list[str] = []
        lst, send = _listener(fired)
        send(K.KEY_LEFTCTRL, 1)
        send(K.KEY_RIGHTCTRL, 1)
        send(K.KEY_RIGHTCTRL, 0)
        assert lst.sgk_modifiers_held() is True
        send(K.KEY_F1, 1)
        assert fired == ["convert"]

    def test_modifiers_held_reflects_state(self) -> None:
        lst, send = _listener([])
        assert lst.sgk_modifiers_held() is False
        send(K.KEY_LEFTSHIFT, 1)
        assert lst.sgk_modifiers_held() is True
        send(K.KEY_LEFTSHIFT, 0)
        assert lst.sgk_modifiers_held() is False

    def test_no_modifier_no_fire(self) -> None:
        fired: list[str] = []
        _, send = _listener(fired)
        send(K.KEY_F1, 1)
        assert fired == []


class _FakeDev:
    def __init__(self, path: str, name: str = "Keyboard", keys=(30,), fd: int = 0,
                 read_error: BaseException | None = None) -> None:
        self.path = path
        self.name = name
        self._keys = list(keys)
        self.fd = fd
        self.closed = False
        self._read_error = read_error

    def capabilities(self):
        return {1: self._keys}

    def close(self) -> None:
        self.closed = True

    def read(self):
        if self._read_error is not None:
            raise self._read_error
        return []


class TestDevices:
    def _patch_evdev(self, monkeypatch, devices: dict[str, _FakeDev]) -> None:
        import evdev

        def make(path):
            if path not in devices:
                raise OSError("gone")
            return devices[path]

        monkeypatch.setattr(evdev, "InputDevice", make)

    def test_own_virtual_device_is_excluded(self, monkeypatch) -> None:
        from sgk_wordwrap.input.base import SGK_VIRTUAL_DEVICE_NAME
        from sgk_wordwrap.input.evdev_backend import SgkEvdevHotkeyListener

        own = _FakeDev("/dev/input/event23", name=SGK_VIRTUAL_DEVICE_NAME)
        real = _FakeDev("/dev/input/event7", name="Keychron K8")
        self._patch_evdev(monkeypatch, {own.path: own, real.path: real})
        assert SgkEvdevHotkeyListener._sgk_open_keyboard(own.path) is None
        assert own.closed is True
        assert SgkEvdevHotkeyListener._sgk_open_keyboard(real.path) is real

    def test_non_keyboard_is_closed(self, monkeypatch) -> None:
        from sgk_wordwrap.input.evdev_backend import SgkEvdevHotkeyListener

        mouse = _FakeDev("/dev/input/event3", name="Mouse", keys=(272,))
        self._patch_evdev(monkeypatch, {mouse.path: mouse})
        assert SgkEvdevHotkeyListener._sgk_open_keyboard(mouse.path) is None
        assert mouse.closed is True

    def test_rescan_adds_new_keyboard_once(self, monkeypatch) -> None:
        import sgk_wordwrap.input.evdev_backend as eb

        new = _FakeDev("/dev/input/event9", fd=9)
        self._patch_evdev(monkeypatch, {new.path: new})
        monkeypatch.setattr(eb.glob, "glob", lambda pattern: [new.path])
        monkeypatch.setattr(eb.os, "access", lambda p, mode: True)
        lst = eb.SgkEvdevHotkeyListener({"convert": "ctrl+f1"})
        fds: dict = {}
        seen: set = set()
        lst._sgk_rescan(fds, seen)
        lst._sgk_rescan(fds, seen)
        assert list(fds) == [9]
        assert seen == {new.path}

    def test_rescan_skips_unreadable_and_retries_later(self, monkeypatch) -> None:
        import sgk_wordwrap.input.evdev_backend as eb

        new = _FakeDev("/dev/input/event9", fd=9)
        self._patch_evdev(monkeypatch, {new.path: new})
        monkeypatch.setattr(eb.glob, "glob", lambda pattern: [new.path])
        readable = {"ok": False}
        monkeypatch.setattr(eb.os, "access", lambda p, mode: readable["ok"])
        lst = eb.SgkEvdevHotkeyListener({"convert": "ctrl+f1"})
        fds: dict = {}
        seen: set = set()
        lst._sgk_rescan(fds, seen)
        assert fds == {}
        readable["ok"] = True
        lst._sgk_rescan(fds, seen)
        assert list(fds) == [9]

    def test_rescan_forgets_removed_paths(self, monkeypatch) -> None:
        import sgk_wordwrap.input.evdev_backend as eb

        monkeypatch.setattr(eb.glob, "glob", lambda pattern: [])
        lst = eb.SgkEvdevHotkeyListener({"convert": "ctrl+f1"})
        seen = {"/dev/input/event5"}
        lst._sgk_rescan({}, seen)
        assert seen == set()

    def test_read_device_lost_on_oserror(self) -> None:
        from sgk_wordwrap.input.evdev_backend import SgkEvdevHotkeyListener

        lst = SgkEvdevHotkeyListener({"convert": "ctrl+f1"})
        dev = _FakeDev("/dev/input/event7", read_error=OSError(19, "No such device"))
        assert lst._sgk_read_device(_FakeEvdev, dev, {}, {}, set()) is False

    def test_read_device_survives_blocking_io(self) -> None:
        from sgk_wordwrap.input.evdev_backend import SgkEvdevHotkeyListener

        lst = SgkEvdevHotkeyListener({"convert": "ctrl+f1"})
        dev = _FakeDev("/dev/input/event7", read_error=BlockingIOError())
        assert lst._sgk_read_device(_FakeEvdev, dev, {}, {}, set()) is True

    def test_callback_exception_does_not_kill_reader(self) -> None:
        from sgk_wordwrap.input.evdev_backend import SgkEvdevHotkeyListener

        lst = SgkEvdevHotkeyListener({"convert": "ctrl+f1"})

        class _Dev(_FakeDev):
            def read(self):
                return [type("E", (), {"type": 1, "code": 59, "value": 1})()]

        def boom(*args):
            raise RuntimeError("bad")

        lst._sgk_handle_key_event = boom
        assert lst._sgk_read_device(_FakeEvdev, _Dev("/dev/input/event7"), {}, {}, set()) is True
