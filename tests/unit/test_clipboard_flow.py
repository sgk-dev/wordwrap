"""Unit tests for the Wayland paste flow of SgkClipboard.

The clipboard subprocess helpers are stubbed so nothing touches the real
wl-clipboard; a fake uinput records paste calls.
"""

from __future__ import annotations

import pytest

from sgk_wordwrap.input.clipboard import SgkClipboard


class _FakeUinput:
    def __init__(self) -> None:
        self.combos: list[str] = []

    def sgk_is_available(self) -> bool:
        return True

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

    board = {"clipboard": "CURRENT_SELECTION", "frozen": False}

    async def fake_run_set(cmd, text):
        sets.append((cmd, text))
        if "--primary" not in cmd and not board["frozen"]:
            board["clipboard"] = None if "--clear" in cmd else text

    async def fake_run_get(cmd):
        gets.append(cmd)
        return board["clipboard"]

    monkeypatch.setattr(cb, "_sgk_run_set", fake_run_set)
    monkeypatch.setattr(cb, "_sgk_run_get", fake_run_get)
    cb._test_sets = sets  # type: ignore[attr-defined]
    cb._test_gets = gets  # type: ignore[attr-defined]
    cb._test_uinput = fake  # type: ignore[attr-defined]
    cb._test_board = board  # type: ignore[attr-defined]
    return cb


@pytest.mark.asyncio
async def test_paste_text_copies_then_pastes(clip) -> None:
    ok = await clip.sgk_paste_text("привет")
    assert ok is True
    assert any(t == "привет" for (_cmd, t) in clip._test_sets)
    assert clip._test_uinput.combos == ["ctrl+v"]


@pytest.mark.asyncio
async def test_paste_text_terminal_combo(clip) -> None:
    await clip.sgk_paste_text("hello", "ctrl+shift+v")
    assert clip._test_uinput.combos == ["ctrl+shift+v"]


@pytest.mark.asyncio
async def test_clear_primary_uses_wl_copy_clear(clip) -> None:
    await clip.sgk_clear_primary()
    assert clip._test_sets[-1][0] == ["wl-copy", "--primary", "--clear"]


@pytest.mark.asyncio
async def test_paste_text_no_wtype_or_ydotool(clip, monkeypatch) -> None:
    """Regression: the Wayland path must not shell out to wtype/ydotool."""
    called: list[str] = []

    async def spy(*args, **kwargs):
        called.append(args[0] if args else "")
        raise AssertionError("subprocess should not be spawned for paste")

    monkeypatch.setattr(
        "sgk_wordwrap.input.clipboard.asyncio.create_subprocess_exec", spy
    )
    await clip.sgk_paste_text("текст")
    assert called == []


@pytest.mark.asyncio
async def test_send_key_routes_to_uinput(clip) -> None:
    await clip.sgk_send_key("ctrl+shift+Left")
    assert clip._test_uinput.combos == ["ctrl+shift+Left"]


@pytest.mark.asyncio
async def test_paste_waits_until_clipboard_holds_text(clip) -> None:
    ok = await clip.sgk_paste_text("привет")
    assert ok is True
    assert clip._test_gets, "paste must read the clipboard back before Ctrl+V"
    assert clip._test_uinput.combos == ["ctrl+v"]


@pytest.mark.asyncio
async def test_paste_aborts_when_clipboard_never_updates(clip, monkeypatch) -> None:
    monkeypatch.setattr("sgk_wordwrap.input.clipboard._VISIBLE_TIMEOUT_S", 0.05)
    clip._test_board["frozen"] = True
    ok = await clip.sgk_paste_text("привет")
    assert ok is False
    assert clip._test_uinput.combos == []


@pytest.mark.asyncio
async def test_set_confirm_reports_visibility(clip, monkeypatch) -> None:
    monkeypatch.setattr("sgk_wordwrap.input.clipboard._VISIBLE_TIMEOUT_S", 0.05)
    assert await clip.sgk_set("marker", confirm=True) is True
    clip._test_board["frozen"] = True
    assert await clip.sgk_set("other", confirm=True) is False
    assert await clip.sgk_set("other") is True
