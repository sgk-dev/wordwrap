"""Unit tests for the Wayland paste flow of SgkClipboard.

The clipboard subprocess helpers are stubbed so nothing touches the real
wl-clipboard; a fake uinput records paste calls.
"""

from __future__ import annotations

import pytest

from sgk_wordwrap.input.clipboard import SgkClipboard


class _FakeUinput:
    def __init__(self) -> None:
        self.pastes: list[bool] = []
        self.combos: list[str] = []

    def sgk_is_available(self) -> bool:
        return True

    def sgk_paste(self, shift: bool = False) -> None:
        self.pastes.append(shift)

    def sgk_send_combo(self, combo: str) -> None:
        self.combos.append(combo)


@pytest.fixture
def clip(monkeypatch: pytest.MonkeyPatch):
    fake = _FakeUinput()
    cb = SgkClipboard(
        action_delay_ms=0,
        clipboard_settle_ms=0,
        paste_settle_ms=0,
        uinput=fake,
    )
    cb._display = "wayland"

    sets: list[tuple[list[str], str]] = []
    gets: list[list[str]] = []

    async def fake_run_set(cmd, text):
        sets.append((cmd, text))

    async def fake_run_get(cmd):
        gets.append(cmd)
        return "CURRENT_SELECTION"

    monkeypatch.setattr(cb, "_sgk_run_set", fake_run_set)
    monkeypatch.setattr(cb, "_sgk_run_get", fake_run_get)
    cb._test_sets = sets  # type: ignore[attr-defined]
    cb._test_gets = gets  # type: ignore[attr-defined]
    cb._test_uinput = fake  # type: ignore[attr-defined]
    return cb


@pytest.mark.asyncio
async def test_type_text_copies_then_pastes(clip) -> None:
    ok = await clip.sgk_type_text("привет")
    assert ok is True
    # wl-copy was invoked with the converted text
    assert any(t == "привет" for (_cmd, t) in clip._test_sets)
    # a plain Ctrl+V paste was sent
    assert clip._test_uinput.pastes == [False]


@pytest.mark.asyncio
async def test_type_text_terminal_uses_shift_paste(clip) -> None:
    await clip.sgk_type_text("hello", terminal=True)
    assert clip._test_uinput.pastes == [True]


@pytest.mark.asyncio
async def test_type_text_no_wtype_or_ydotool(clip, monkeypatch) -> None:
    """Regression: the Wayland path must not shell out to wtype/ydotool."""
    called: list[str] = []

    async def spy(*args, **kwargs):
        called.append(args[0] if args else "")
        raise AssertionError("subprocess should not be spawned for paste")

    monkeypatch.setattr(
        "sgk_wordwrap.input.clipboard.asyncio.create_subprocess_exec", spy
    )
    await clip.sgk_type_text("текст")
    assert called == []


@pytest.mark.asyncio
async def test_send_key_routes_to_uinput(clip) -> None:
    await clip.sgk_send_key("ctrl+shift+Left")
    assert clip._test_uinput.combos == ["ctrl+shift+Left"]
