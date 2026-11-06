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


class _FakeProc:
    def __init__(self, out: bytes = b"", rc: int = 0, hang: bool = False) -> None:
        self._out = out
        self.returncode = None
        self._rc = rc
        self._hang = hang
        self.killed = False
        self.stdin_data = None

    async def communicate(self, data=None):
        import asyncio

        self.stdin_data = data
        if self._hang:
            await asyncio.sleep(10)
        self.returncode = self._rc
        return self._out, b""

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    async def wait(self) -> int:
        return self.returncode


@pytest.fixture
def raw_clip(monkeypatch: pytest.MonkeyPatch):
    cb = SgkClipboard(action_delay_ms=0, paste_settle_ms=0, uinput=_FakeUinput())
    cb._display = "wayland"
    script: dict[str, _FakeProc] = {}
    calls: list[list[str]] = []

    async def fake_exec(*cmd, **kwargs):
        calls.append(list(cmd))
        for key, proc in script.items():
            if " ".join(cmd).startswith(key):
                return proc
        return _FakeProc()

    monkeypatch.setattr("sgk_wordwrap.input.clipboard.asyncio.create_subprocess_exec", fake_exec)
    cb._script = script  # type: ignore[attr-defined]
    cb._calls = calls  # type: ignore[attr-defined]
    return cb


@pytest.mark.asyncio
async def test_get_timeout_kills_process(raw_clip, monkeypatch) -> None:
    monkeypatch.setattr("sgk_wordwrap.input.clipboard._CLIPBOARD_TIMEOUT", 0.01)
    proc = _FakeProc(hang=True)
    raw_clip._script["wl-paste"] = proc
    assert await raw_clip.sgk_get() is None
    assert proc.killed is True


@pytest.mark.asyncio
async def test_set_timeout_kills_process(raw_clip, monkeypatch) -> None:
    monkeypatch.setattr("sgk_wordwrap.input.clipboard._CLIPBOARD_TIMEOUT", 0.01)
    proc = _FakeProc(hang=True)
    raw_clip._script["wl-copy"] = proc
    assert await raw_clip.sgk_set("x") is False
    assert proc.killed is True


@pytest.mark.asyncio
async def test_set_nonzero_exit_keeps_flow(raw_clip) -> None:
    raw_clip._script["wl-copy"] = _FakeProc(rc=1)
    assert await raw_clip.sgk_set("x") is True


@pytest.mark.asyncio
async def test_get_nonzero_exit_returns_none(raw_clip) -> None:
    raw_clip._script["wl-paste"] = _FakeProc(out=b"x", rc=1)
    assert await raw_clip.sgk_get() is None


@pytest.mark.asyncio
async def test_get_primary_failure_returns_none(raw_clip, monkeypatch) -> None:
    monkeypatch.setattr("sgk_wordwrap.input.clipboard._CLIPBOARD_TIMEOUT", 0.01)
    raw_clip._script["wl-paste"] = _FakeProc(hang=True)
    assert await raw_clip.sgk_get_primary() is None


@pytest.mark.asyncio
async def test_snapshot_picks_first_non_text_type(raw_clip) -> None:
    raw_clip._script["wl-paste --list-types"] = _FakeProc(
        out=b"x-kde-passwordManagerHint\nimage/png\ntext/plain\n"
    )
    raw_clip._script["wl-paste --type image/png"] = _FakeProc(out=b"\x89PNG")
    blob = await raw_clip.sgk_snapshot_non_text()
    assert blob.mime == "image/png"
    assert blob.data == b"\x89PNG"


@pytest.mark.asyncio
async def test_snapshot_empty_clipboard_is_none(raw_clip) -> None:
    raw_clip._script["wl-paste --list-types"] = _FakeProc(out=b"", rc=1)
    assert await raw_clip.sgk_snapshot_non_text() is None


@pytest.mark.asyncio
async def test_snapshot_text_only_is_none(raw_clip) -> None:
    raw_clip._script["wl-paste --list-types"] = _FakeProc(out=b"text/plain\nUTF8_STRING\n")
    assert await raw_clip.sgk_snapshot_non_text() is None


@pytest.mark.asyncio
async def test_snapshot_too_big_is_none(raw_clip, monkeypatch) -> None:
    monkeypatch.setattr("sgk_wordwrap.input.clipboard._BLOB_MAX_BYTES", 3)
    raw_clip._script["wl-paste --list-types"] = _FakeProc(out=b"image/png\n")
    raw_clip._script["wl-paste --type image/png"] = _FakeProc(out=b"12345")
    assert await raw_clip.sgk_snapshot_non_text() is None


@pytest.mark.asyncio
async def test_snapshot_not_on_x11(raw_clip) -> None:
    raw_clip._display = "x11"
    assert await raw_clip.sgk_snapshot_non_text() is None
    assert raw_clip._calls == []


@pytest.mark.asyncio
async def test_set_blob_uses_mime_type(raw_clip) -> None:
    from sgk_wordwrap.input.clipboard import SgkClipboardBlob

    proc = _FakeProc()
    raw_clip._script["wl-copy"] = proc
    assert await raw_clip.sgk_set_blob(SgkClipboardBlob("image/png", b"PNG")) is True
    assert raw_clip._calls[-1] == ["wl-copy", "--type", "image/png"]
    assert proc.stdin_data == b"PNG"


@pytest.mark.asyncio
async def test_clear_uses_wl_copy_clear(raw_clip) -> None:
    await raw_clip.sgk_clear()
    assert raw_clip._calls[-1] == ["wl-copy", "--clear"]


@pytest.mark.asyncio
async def test_paste_returns_false_when_uinput_unavailable(raw_clip) -> None:
    raw_clip._uinput = None
    assert await raw_clip.sgk_paste_text("x") is False


class _RepeatUinput(_FakeUinput):
    def __init__(self) -> None:
        super().__init__()
        self.repeats: list[tuple[str, int]] = []

    def sgk_send_combo_repeat(self, combo: str, count: int) -> None:
        self.repeats.append((combo, count))


@pytest.mark.asyncio
async def test_send_key_repeat_routes_to_uinput(clip) -> None:
    fake = _RepeatUinput()
    clip._uinput = fake
    await clip.sgk_send_key_repeat("super+space", 2)
    assert fake.repeats == [("super+space", 2)]


@pytest.mark.asyncio
async def test_send_key_repeat_single_is_plain_combo(clip) -> None:
    await clip.sgk_send_key_repeat("super+space", 1)
    assert clip._test_uinput.combos == ["super+space"]


def test_is_text_safe() -> None:
    assert SgkClipboard.sgk_is_text_safe("hello") is True
    assert SgkClipboard.sgk_is_text_safe("") is False
    assert SgkClipboard.sgk_is_text_safe("   ") is False
    assert SgkClipboard.sgk_is_text_safe("a" * 10, max_length=10) is True
    assert SgkClipboard.sgk_is_text_safe("a" * 11, max_length=10) is False
    assert SgkClipboard.sgk_is_text_safe("  " + "a" * 10 + "  ", max_length=10) is True
    assert SgkClipboard.sgk_is_text_safe(None) is False  # type: ignore[arg-type]
    assert SgkClipboard.sgk_is_text_safe(123) is False  # type: ignore[arg-type]
