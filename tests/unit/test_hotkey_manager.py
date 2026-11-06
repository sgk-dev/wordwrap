from __future__ import annotations

import pytest

import sgk_wordwrap.core.hotkey_manager as hm
from sgk_wordwrap.core.hotkey_manager import SgkHotkeyManager


class _FakeLoop:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def call_soon_threadsafe(self, fn, *args) -> None:
        self.calls.append((fn, args))


class _FakeBackend:
    def __init__(self, available: bool = True, held: bool = False) -> None:
        self.available = available
        self.held = held
        self.started = False

    def sgk_is_available(self) -> bool:
        return self.available

    def sgk_start(self, cb) -> None:
        self.started = True

    def sgk_stop(self) -> None:
        pass

    def sgk_modifiers_held(self) -> bool:
        return self.held


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch):
    now = {"t": 100.0}
    monkeypatch.setattr(hm.time, "monotonic", lambda: now["t"])
    return now


def _manager(loop: _FakeLoop) -> SgkHotkeyManager:
    m = SgkHotkeyManager()
    m._loop = loop
    m.sgk_set_handler(lambda mode: None)
    m.sgk_set_toggle_handler(lambda: None)
    return m


def test_convert_dispatched_with_mode_name(clock) -> None:
    loop = _FakeLoop()
    m = _manager(loop)
    m._sgk_on_hotkey_raw("convert_terminal")
    assert loop.calls[0][1] == ("convert_terminal",)


def test_same_hotkey_debounced_within_300ms(clock) -> None:
    loop = _FakeLoop()
    m = _manager(loop)
    m._sgk_on_hotkey_raw("convert")
    clock["t"] += 0.1
    m._sgk_on_hotkey_raw("convert")
    clock["t"] += 0.3
    m._sgk_on_hotkey_raw("convert")
    assert len(loop.calls) == 2


def test_different_hotkeys_not_debounced_together(clock) -> None:
    loop = _FakeLoop()
    m = _manager(loop)
    m._sgk_on_hotkey_raw("convert")
    m._sgk_on_hotkey_raw("convert_last_word")
    assert len(loop.calls) == 2


def test_paused_drops_convert_but_not_toggle(clock) -> None:
    loop = _FakeLoop()
    m = _manager(loop)
    m.sgk_pause()
    m._sgk_on_hotkey_raw("convert")
    m._sgk_on_hotkey_raw("toggle")
    assert len(loop.calls) == 1
    assert loop.calls[0][0] is m._toggle_handler


def test_unknown_name_ignored(clock) -> None:
    loop = _FakeLoop()
    m = _manager(loop)
    m._sgk_on_hotkey_raw("nonsense")
    assert loop.calls == []


def test_user_hotkeys_override_defaults_keep_others() -> None:
    m = SgkHotkeyManager({"convert": "ctrl+f9"})
    assert m._hotkeys["convert"] == "ctrl+f9"
    assert m._hotkeys["toggle"] == "ctrl+pause"


def test_modifiers_held_false_without_backend() -> None:
    assert SgkHotkeyManager().sgk_modifiers_held() is False


def test_modifiers_held_reads_backend() -> None:
    m = SgkHotkeyManager()
    m._backend = _FakeBackend(held=True)
    assert m.sgk_modifiers_held() is True


def test_start_without_available_backend_not_listening(monkeypatch) -> None:
    m = SgkHotkeyManager()
    monkeypatch.setattr(m, "_sgk_pick_backend", lambda: _FakeBackend(available=False))
    m.sgk_start(_FakeLoop())
    assert m.sgk_is_listening() is False


def test_start_with_backend_listens(monkeypatch) -> None:
    m = SgkHotkeyManager()
    backend = _FakeBackend()
    monkeypatch.setattr(m, "_sgk_pick_backend", lambda: backend)
    m.sgk_start(_FakeLoop())
    assert m.sgk_is_listening() is True
    assert backend.started is True
