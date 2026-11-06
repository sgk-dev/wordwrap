"""Unit tests for SgkTextProcessor (mocked dependencies).

Text acquisition model: the processor calls clipboard.sgk_get() once to save the
user's clipboard, writes a private marker with sgk_set(), Ctrl+Insert's the
selection and reads sgk_get() again: still the marker means nothing is selected.
`get_returns` is the full sgk_get() call sequence [saved, after_first_copy,
(after_word_select_copy)]; the MARKER sentinel stands for "clipboard unchanged,
i.e. whatever was last written with sgk_set()". The terminal flow instead reads
clipboard.sgk_get_primary() (the `primary` kwarg).
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from sgk_wordwrap.core.layout_manager import SgkLayoutManager
from sgk_wordwrap.core.text_processor import SgkTextProcessor
from sgk_wordwrap.input.clipboard import SgkClipboard
from sgk_wordwrap.layouts.detector import SgkFieldDetector
from sgk_wordwrap.layouts.mapper import SgkLayoutMapper

MARKER = object()


class _FakeGnome:
    def __init__(
        self,
        window: str,
        active: list[str],
        mru: list[str] | None = None,
        per_window: bool = True,
        ibus: bool = True,
        mru_lag_reads: int = 0,
        swallow_presses: int = 0,
    ) -> None:
        self.inmem = [window] + [a for a in active if a != window]
        self.mru = list(mru) if mru is not None else list(self.inmem)
        self.per_window = per_window
        self.ibus = ibus
        self.mru_lag_reads = mru_lag_reads
        self.swallow_presses = swallow_presses
        self.presses: list[int] = []
        self._pending: list[str] | None = None
        self._lag_left = 0

    @property
    def window(self) -> str:
        return self.inmem[0]

    async def press(self, combo: str, count: int) -> None:
        self.presses.append(count)
        if self.swallow_presses:
            self.swallow_presses -= 1
            return
        new = self.inmem[count % len(self.inmem)]
        self.inmem = [new] + [x for x in self.inmem if x != new]
        self._pending = list(self.inmem)
        self._lag_left = self.mru_lag_reads
        self._sgk_flush()

    def _sgk_flush(self) -> None:
        if self._pending is not None and self._lag_left <= 0:
            self.mru = self._pending
            self._pending = None

    def live(self) -> str | None:
        return self.window if self.ibus else None

    def mru_first(self) -> str:
        self._lag_left -= 1
        self._sgk_flush()
        return self.mru[0]

    def mru_all(self) -> list[str]:
        return list(self.mru)


@pytest.fixture(autouse=True)
def _fast_switch_polls(monkeypatch: pytest.MonkeyPatch) -> None:
    import sgk_wordwrap.core.text_processor as tp

    monkeypatch.setattr(tp, "_SWITCH_POLL_S", 0.001)
    monkeypatch.setattr(tp, "_SWITCH_WAIT_LIVE_S", 0.02)
    monkeypatch.setattr(tp, "_SWITCH_WAIT_MRU_S", 0.02)


def _make_processor(
    get_returns: list | None = None,
    current_layout: str = "en",
    next_layout: str = "ru",
    detected_layout: str | None = "en",
    active_layouts: list[str] | None = None,
    sensitive: bool = False,
    converted: str = "CONVERTED",
    fallback_to_word: bool = True,
    restore_clipboard: bool = True,
    primary: str | None = None,
    terminal_erase: str = "line",
    set_ok: bool = True,
    copy_settle_ms: int = 0,
    modifiers_held=None,
    gnome: _FakeGnome | None = None,
    snapshot=None,
) -> SgkTextProcessor:
    clipboard = MagicMock(spec=SgkClipboard)
    state = {"last_set": None}
    seq = iter(get_returns or [])

    async def _set(text: str, confirm: bool = False) -> bool:
        if set_ok:
            state["last_set"] = text
        return set_ok

    async def _get() -> str | None:
        try:
            value = next(seq)
        except StopIteration:
            return None
        return state["last_set"] if value is MARKER else value

    clipboard.sgk_get = AsyncMock(side_effect=_get)
    clipboard.sgk_set = AsyncMock(side_effect=_set)
    clipboard.sgk_get_primary = AsyncMock(return_value=primary)
    clipboard.sgk_clear = AsyncMock()
    clipboard.sgk_clear_primary = AsyncMock()
    clipboard.sgk_paste_text = AsyncMock(return_value=True)
    clipboard.sgk_backspace = AsyncMock()
    clipboard.sgk_send_key = AsyncMock()
    clipboard.sgk_snapshot_non_text = AsyncMock(return_value=snapshot)
    clipboard.sgk_set_blob = AsyncMock(return_value=True)

    active = active_layouts or ["en", "ru"]
    if gnome is None:
        gnome = _FakeGnome(window=current_layout, active=active)
    clipboard.sgk_send_key_repeat = AsyncMock(side_effect=gnome.press)

    layout_manager = MagicMock(spec=SgkLayoutManager)
    layout_manager.sgk_get_current_layout.return_value = current_layout
    layout_manager.sgk_get_next_layout.return_value = next_layout
    layout_manager.sgk_get_active_layouts.return_value = active
    layout_manager.sgk_switch_to = MagicMock()
    layout_manager.sgk_layout_matches.return_value = True
    layout_manager.sgk_get_switch_shortcut.return_value = "super+space"
    layout_manager.sgk_uses_shortcut_switch.return_value = True
    layout_manager.sgk_per_window.side_effect = lambda: gnome.per_window
    layout_manager.sgk_get_live_layout.side_effect = gnome.live
    layout_manager.sgk_get_mru_layout.side_effect = gnome.mru_first
    layout_manager.sgk_get_mru_layouts.side_effect = gnome.mru_all

    mapper = MagicMock(spec=SgkLayoutMapper)
    mapper.sgk_has_map.return_value = True
    mapper.sgk_convert.return_value = converted
    mapper.sgk_detect_likely_layout.return_value = detected_layout

    detector = MagicMock(spec=SgkFieldDetector)
    detector.sgk_is_sensitive_context.return_value = sensitive
    detector.sgk_get_active_window_info.return_value = ("firefox", "Navigator", "T")

    processor = SgkTextProcessor(
        clipboard=clipboard,
        layout_manager=layout_manager,
        mapper=mapper,
        detector=detector,
        max_text_length=10000,
        fallback_to_word=fallback_to_word,
        restore_clipboard=restore_clipboard,
        settle_ms=0,
        copy_settle_ms=copy_settle_ms,
        layout_settle_ms=0,
        terminal_settle_ms=0,
        terminal_erase=terminal_erase,
        modifiers_held=modifiers_held,
    )
    processor._sgk_switch_layout = AsyncMock(side_effect=processor._sgk_switch_layout)
    processor._gnome = gnome
    return processor


def _sent_keys(p: SgkTextProcessor) -> list[str]:
    return [c.args[0] for c in p._clipboard.sgk_send_key.call_args_list]


def _set_values(p: SgkTextProcessor) -> list[str]:
    return [c.args[0] for c in p._clipboard.sgk_set.call_args_list]


@pytest.mark.asyncio
async def test_selected_text_converted_and_pasted() -> None:
    p = _make_processor(get_returns=["orig", "ghbdtn"], converted="привет")
    await p.sgk_process()
    assert "ctrl+insert" in _sent_keys(p)
    p._clipboard.sgk_paste_text.assert_called_once_with("привет", "ctrl+v")
    p._sgk_switch_layout.assert_called_once_with("ru")


@pytest.mark.asyncio
async def test_selection_equal_to_saved_clipboard_is_still_converted() -> None:
    p = _make_processor(get_returns=["ghbdtn", "ghbdtn"], converted="привет")
    await p.sgk_process()
    assert "ctrl+shift+Left" not in _sent_keys(p)
    p._clipboard.sgk_paste_text.assert_called_once_with("привет", "ctrl+v")


@pytest.mark.asyncio
async def test_marker_is_written_before_copy_and_original_restored() -> None:
    p = _make_processor(get_returns=["orig", "ghbdtn"], converted="привет")
    await p.sgk_process()
    values = _set_values(p)
    assert values[0].startswith("sgk-wordwrap-")
    assert values[-1] == "orig"


@pytest.mark.asyncio
async def test_layout_switch_presses_shortcut_once_and_lands_on_target() -> None:
    p = _make_processor(get_returns=["orig", "ghbdtn"], converted="привет")
    await p.sgk_process()
    p._sgk_switch_layout.assert_called_once_with("ru")
    assert p._gnome.presses == [1]
    assert p._gnome.window == "ru"
    p._layout_manager.sgk_switch_to.assert_not_called()


@pytest.mark.asyncio
async def test_second_hotkey_while_busy_is_dropped() -> None:
    p = _make_processor(get_returns=["orig", "ghbdtn"], converted="привет")
    gate = asyncio.Event()
    original = p._clipboard.sgk_paste_text

    async def slow_paste(text: str, combo: str) -> bool:
        await gate.wait()
        return await original(text, combo)

    p._clipboard.sgk_paste_text = AsyncMock(side_effect=slow_paste)
    first = asyncio.create_task(p.sgk_process())
    await asyncio.sleep(0)
    await p.sgk_process()
    gate.set()
    await first
    assert p._clipboard.sgk_paste_text.call_count == 1
    assert p._busy is False


@pytest.mark.asyncio
async def test_terminal_mode_clears_line_then_pastes() -> None:
    p = _make_processor(
        get_returns=["orig"], primary="руддщ", detected_layout="ru", converted="hello"
    )
    await p.sgk_process(mode="convert_terminal")
    assert _sent_keys(p) == ["ctrl+a", "ctrl+k"]
    p._clipboard.sgk_paste_text.assert_called_once_with("hello", "ctrl+shift+v")
    p._sgk_switch_layout.assert_called_once_with("en")


@pytest.mark.asyncio
async def test_terminal_mode_clears_primary_after_use() -> None:
    p = _make_processor(
        get_returns=["orig"], primary="руддщ", detected_layout="ru", converted="hello"
    )
    await p.sgk_process(mode="convert_terminal")
    p._clipboard.sgk_clear_primary.assert_called_once()


@pytest.mark.asyncio
async def test_terminal_mode_strips_selection_whitespace() -> None:
    p = _make_processor(
        get_returns=["orig"], primary="  руддщ \n", detected_layout="ru",
        converted="hello", terminal_erase="backspace",
    )
    await p.sgk_process(mode="convert_terminal")
    p._clipboard.sgk_backspace.assert_called_once_with(5)


@pytest.mark.asyncio
async def test_terminal_mode_backspace_mode() -> None:
    p = _make_processor(
        get_returns=["orig"], primary="руддщ", detected_layout="ru",
        converted="hello", terminal_erase="backspace",
    )
    await p.sgk_process(mode="convert_terminal")
    p._clipboard.sgk_backspace.assert_called_once_with(5)
    p._clipboard.sgk_paste_text.assert_called_once_with("hello", "ctrl+shift+v")


@pytest.mark.asyncio
async def test_terminal_mode_no_selection_is_noop() -> None:
    p = _make_processor(get_returns=["orig"], primary="", converted="x")
    await p.sgk_process(mode="convert_terminal")
    p._clipboard.sgk_send_key.assert_not_called()
    p._clipboard.sgk_paste_text.assert_not_called()
    p._clipboard.sgk_set.assert_not_called()
    p._clipboard.sgk_clear_primary.assert_not_called()


@pytest.mark.asyncio
async def test_terminal_mode_refuses_multiline_selection() -> None:
    p = _make_processor(
        get_returns=["orig"], primary="line one\nline two", converted="x"
    )
    await p.sgk_process(mode="convert_terminal")
    p._clipboard.sgk_send_key.assert_not_called()
    p._clipboard.sgk_backspace.assert_not_called()
    p._clipboard.sgk_paste_text.assert_not_called()


@pytest.mark.asyncio
async def test_terminal_mode_unchanged_text_does_not_touch_line() -> None:
    p = _make_processor(get_returns=["orig"], primary="hello", converted="hello")
    await p.sgk_process(mode="convert_terminal")
    p._clipboard.sgk_send_key.assert_not_called()
    p._clipboard.sgk_paste_text.assert_not_called()


@pytest.mark.asyncio
async def test_last_word_mode_forces_word_selection() -> None:
    p = _make_processor(get_returns=["orig", "wordtext"], converted="ПЕРЕВОД")
    await p.sgk_process(mode="convert_last_word")
    keys = _sent_keys(p)
    assert "ctrl+shift+Left" in keys
    assert keys.count("ctrl+insert") == 1
    p._clipboard.sgk_paste_text.assert_called_once_with("ПЕРЕВОД", "ctrl+v")


@pytest.mark.asyncio
async def test_direction_follows_detected_source_not_active_layout() -> None:
    p = _make_processor(
        get_returns=["orig", "ghbdtn"],
        current_layout="ru",
        detected_layout="en",
        converted="привет",
    )
    await p.sgk_process()
    p._mapper.sgk_convert.assert_called_once_with("ghbdtn", "en", "ru")
    p._sgk_switch_layout.assert_called_once_with("ru")


@pytest.mark.asyncio
async def test_reverse_direction_ru_to_en() -> None:
    p = _make_processor(
        get_returns=["orig", "руддщ"],
        detected_layout="ru",
        converted="hello",
    )
    await p.sgk_process()
    p._mapper.sgk_convert.assert_called_once_with("руддщ", "ru", "en")
    p._sgk_switch_layout.assert_called_once_with("en")


@pytest.mark.asyncio
async def test_direction_falls_back_to_current_layout_when_undetectable() -> None:
    p = _make_processor(
        get_returns=["orig", "123"],
        detected_layout=None,
        current_layout="en",
        converted="XXX",
    )
    await p.sgk_process()
    p._mapper.sgk_convert.assert_called_once_with("123", "en", "ru")


@pytest.mark.asyncio
async def test_no_selection_falls_back_to_word() -> None:
    p = _make_processor(get_returns=["orig", MARKER, MARKER, "wordtext"], converted="WT_RU")
    await p.sgk_process()
    assert "ctrl+shift+Left" in _sent_keys(p)
    p._clipboard.sgk_paste_text.assert_called_once_with("WT_RU", "ctrl+v")


@pytest.mark.asyncio
async def test_no_selection_no_fallback_is_noop() -> None:
    p = _make_processor(get_returns=["orig", MARKER, MARKER], fallback_to_word=False)
    await p.sgk_process()
    p._clipboard.sgk_paste_text.assert_not_called()
    p._sgk_switch_layout.assert_not_called()
    assert _set_values(p)[-1] == "orig"


@pytest.mark.asyncio
async def test_marker_write_failure_falls_back_to_saved_comparison() -> None:
    p = _make_processor(get_returns=["orig", "orig", "orig", "wordtext"], set_ok=False)
    await p.sgk_process()
    assert "ctrl+shift+Left" in _sent_keys(p)
    p._clipboard.sgk_paste_text.assert_called_once()


@pytest.mark.asyncio
async def test_sensitive_context_skipped_without_touching_clipboard() -> None:
    p = _make_processor(sensitive=True)
    await p.sgk_process()
    p._clipboard.sgk_get.assert_not_called()
    p._clipboard.sgk_send_key.assert_not_called()
    p._clipboard.sgk_paste_text.assert_not_called()
    p._sgk_switch_layout.assert_not_called()


@pytest.mark.asyncio
async def test_no_text_acquired_skipped() -> None:
    p = _make_processor(get_returns=["orig", MARKER, MARKER, MARKER])
    await p.sgk_process()
    p._sgk_switch_layout.assert_not_called()


@pytest.mark.asyncio
async def test_text_too_long_skipped_and_clipboard_restored() -> None:
    p = _make_processor(get_returns=["orig", "a" * 20000])
    await p.sgk_process()
    p._clipboard.sgk_paste_text.assert_not_called()
    p._sgk_switch_layout.assert_not_called()
    assert _set_values(p)[-1] == "orig"


@pytest.mark.asyncio
async def test_no_map_skipped() -> None:
    p = _make_processor(get_returns=["orig", "sometext"])
    p._mapper.sgk_has_map.return_value = False
    await p.sgk_process()
    p._sgk_switch_layout.assert_not_called()


@pytest.mark.asyncio
async def test_conversion_is_noop_when_nothing_changes() -> None:
    p = _make_processor(get_returns=["orig", "hello"], converted="hello")
    await p.sgk_process()
    p._clipboard.sgk_paste_text.assert_not_called()
    p._sgk_switch_layout.assert_not_called()
    assert _set_values(p)[-1] == "orig"


@pytest.mark.asyncio
async def test_clipboard_restored_after_successful_conversion() -> None:
    p = _make_processor(get_returns=["MY_SAVED", "text"], converted="CONV")
    await p.sgk_process()
    assert _set_values(p)[-1] == "MY_SAVED"


@pytest.mark.asyncio
async def test_restore_disabled_keeps_converted_text_in_clipboard() -> None:
    p = _make_processor(
        get_returns=["MY_SAVED", "text"], converted="CONV", restore_clipboard=False
    )
    await p.sgk_process()
    assert "MY_SAVED" not in _set_values(p)
    p._clipboard.sgk_clear.assert_not_called()


@pytest.mark.asyncio
async def test_restore_disabled_still_cleans_up_after_abort() -> None:
    p = _make_processor(get_returns=["MY_SAVED", MARKER, MARKER, MARKER], restore_clipboard=False)
    await p.sgk_process()
    assert _set_values(p)[-1] == "MY_SAVED"


@pytest.mark.asyncio
async def test_non_text_clipboard_is_cleared_not_filled_with_garbage() -> None:
    p = _make_processor(get_returns=[None, "text"], converted="CONV")
    await p.sgk_process()
    p._clipboard.sgk_clear.assert_called_once()
    assert all(v.startswith("sgk-wordwrap-") for v in _set_values(p))


@pytest.mark.asyncio
async def test_slow_app_clipboard_is_polled_until_it_changes() -> None:
    p = _make_processor(
        get_returns=["orig", MARKER, MARKER, "ghbdtn"],
        converted="привет",
        fallback_to_word=False,
        copy_settle_ms=500,
    )
    await p.sgk_process()
    assert "ctrl+shift+Left" not in _sent_keys(p)
    p._clipboard.sgk_paste_text.assert_called_once_with("привет", "ctrl+v")
    assert p._clipboard.sgk_get.call_count == 4


@pytest.mark.asyncio
async def test_copy_is_retried_before_word_fallback() -> None:
    p = _make_processor(get_returns=["orig", MARKER, "ghbdtn"], converted="привет")
    await p.sgk_process()
    keys = _sent_keys(p)
    assert keys.count("ctrl+insert") == 2
    assert "ctrl+shift+Left" not in keys
    p._clipboard.sgk_paste_text.assert_called_once_with("привет", "ctrl+v")


@pytest.mark.asyncio
async def test_waits_for_physical_modifiers_to_be_released() -> None:
    held = {"n": 3}

    def modifiers_held() -> bool:
        held["n"] -= 1
        return held["n"] > 0

    p = _make_processor(
        get_returns=["orig", "ghbdtn"], converted="привет", modifiers_held=modifiers_held
    )
    await p.sgk_process()
    assert held["n"] <= 0
    p._clipboard.sgk_paste_text.assert_called_once()


@pytest.mark.asyncio
async def test_marker_is_written_with_confirmation() -> None:
    p = _make_processor(get_returns=["orig", "ghbdtn"], converted="привет")
    await p.sgk_process()
    first = p._clipboard.sgk_set.call_args_list[0]
    assert first.args[0].startswith("sgk-wordwrap-")
    assert first.kwargs.get("confirm") is True


@pytest.mark.asyncio
async def test_late_marker_is_never_treated_as_selection() -> None:
    p = _make_processor(
        get_returns=["orig", "sgk-wordwrap-stale", "sgk-wordwrap-stale", "wordtext"],
        set_ok=False,
        converted="CONV",
    )
    await p.sgk_process()
    assert "ctrl+shift+Left" in _sent_keys(p)
    p._clipboard.sgk_paste_text.assert_called_once_with("CONV", "ctrl+v")


@pytest.mark.asyncio
async def test_failed_paste_keeps_layout_and_restores_clipboard() -> None:
    p = _make_processor(get_returns=["orig", "ghbdtn"], converted="привет")
    p._clipboard.sgk_paste_text = AsyncMock(return_value=False)
    await p.sgk_process()
    p._sgk_switch_layout.assert_not_called()
    assert _set_values(p)[-1] == "orig"


@pytest.mark.asyncio
async def test_terminal_failed_paste_keeps_primary_and_layout() -> None:
    p = _make_processor(primary="ghbdtn", converted="привет")
    p._clipboard.sgk_paste_text = AsyncMock(return_value=False)
    await p.sgk_process("convert_terminal")
    p._clipboard.sgk_clear_primary.assert_not_called()
    p._sgk_switch_layout.assert_not_called()


@pytest.mark.asyncio
async def test_switch_presses_once_when_stale_mru_already_says_target() -> None:
    gnome = _FakeGnome(window="en", active=["en", "ru"], mru=["ru", "en"])
    p = _make_processor(get_returns=["orig", "ghbdtn"], converted="привет", gnome=gnome)
    await p.sgk_process()
    assert gnome.presses == [1]
    assert gnome.window == "ru"


@pytest.mark.asyncio
async def test_switch_skipped_when_live_layout_is_target() -> None:
    gnome = _FakeGnome(window="ru", active=["en", "ru"], mru=["en", "ru"])
    p = _make_processor(get_returns=["orig", "ghbdtn"], converted="привет", gnome=gnome)
    await p.sgk_process()
    assert gnome.presses == []
    assert gnome.window == "ru"


@pytest.mark.asyncio
async def test_switch_without_ibus_already_in_target_presses_twice() -> None:
    gnome = _FakeGnome(window="ru", active=["en", "ru"], mru=["en", "ru"], ibus=False)
    p = _make_processor(get_returns=["orig", "ghbdtn"], converted="привет", gnome=gnome)
    await p.sgk_process()
    assert gnome.presses == [1, 1]
    assert gnome.window == "ru"


@pytest.mark.asyncio
async def test_switch_without_ibus_stale_mru_target_presses_once() -> None:
    gnome = _FakeGnome(window="en", active=["en", "ru"], mru=["ru", "en"], ibus=False)
    p = _make_processor(get_returns=["orig", "ghbdtn"], converted="привет", gnome=gnome)
    await p.sgk_process()
    assert gnome.presses == [1]
    assert gnome.window == "ru"


@pytest.mark.asyncio
async def test_switch_without_ibus_needs_change_not_stale_target() -> None:
    gnome = _FakeGnome(
        window="ru", active=["en", "ru"], mru=["ru", "en"], ibus=False, mru_lag_reads=3
    )
    p = _make_processor(get_returns=["orig", "ghbdtn"], converted="привет", gnome=gnome)
    await p.sgk_process()
    assert gnome.window == "ru"
    assert len(gnome.presses) == 2


@pytest.mark.asyncio
async def test_switch_shared_layout_trusts_mru_and_skips() -> None:
    gnome = _FakeGnome(window="ru", active=["en", "ru"], per_window=False)
    p = _make_processor(get_returns=["orig", "ghbdtn"], converted="привет", gnome=gnome)
    await p.sgk_process()
    assert gnome.presses == []


@pytest.mark.asyncio
async def test_switch_shared_layout_presses_once() -> None:
    gnome = _FakeGnome(window="en", active=["en", "ru"], per_window=False)
    p = _make_processor(get_returns=["orig", "ghbdtn"], converted="привет", gnome=gnome)
    await p.sgk_process()
    assert gnome.presses == [1]
    assert gnome.window == "ru"


@pytest.mark.asyncio
async def test_switch_lagging_readback_never_toggles_back() -> None:
    gnome = _FakeGnome(window="en", active=["en", "ru"], per_window=False, mru_lag_reads=1000)
    p = _make_processor(get_returns=["orig", "ghbdtn"], converted="привет", gnome=gnome)
    await p.sgk_process()
    assert gnome.presses == [1]
    assert gnome.window == "ru"


@pytest.mark.asyncio
async def test_switch_slightly_late_readback_presses_once() -> None:
    gnome = _FakeGnome(window="en", active=["en", "ru"], per_window=False, mru_lag_reads=3)
    p = _make_processor(get_returns=["orig", "ghbdtn"], converted="привет", gnome=gnome)
    await p.sgk_process()
    assert gnome.presses == [1]
    assert gnome.window == "ru"


@pytest.mark.asyncio
async def test_switch_lost_press_is_not_retried_blindly() -> None:
    gnome = _FakeGnome(window="en", active=["en", "ru"], swallow_presses=1)
    p = _make_processor(get_returns=["orig", "ghbdtn"], converted="привет", gnome=gnome)
    assert await p._sgk_switch_layout("ru") == "en"
    assert gnome.presses == [1]


@pytest.mark.asyncio
async def test_switch_returns_final_layout() -> None:
    p = _make_processor()
    assert await p._sgk_switch_layout("ru") == "ru"


@pytest.mark.asyncio
async def test_switch_three_layouts_taps_to_mru_index() -> None:
    gnome = _FakeGnome(window="en", active=["en", "ru", "uk"])
    p = _make_processor(gnome=gnome, active_layouts=["en", "ru", "uk"])
    assert await p._sgk_switch_layout("uk") == "uk"
    assert gnome.presses == [2]


@pytest.mark.asyncio
async def test_switch_three_layouts_corrects_wrong_estimate() -> None:
    gnome = _FakeGnome(window="en", active=["en", "ru", "uk"], mru=["en", "ru", "uk"])
    gnome.inmem = ["en", "uk", "ru"]
    p = _make_processor(gnome=gnome, active_layouts=["en", "ru", "uk"])
    assert await p._sgk_switch_layout("uk") == "uk"
    assert gnome.presses == [2, 2]


@pytest.mark.asyncio
async def test_switch_two_layouts_uses_single_tap() -> None:
    gnome = _FakeGnome(window="en", active=["en", "ru"])
    p = _make_processor(gnome=gnome)
    await p._sgk_switch_layout("ru")
    p._clipboard.sgk_send_key_repeat.assert_called_once_with("super+space", 1)


@pytest.mark.asyncio
async def test_legacy_backend_uses_switch_to_and_skips_shortcut_on_match() -> None:
    p = _make_processor()
    p._layout_manager.sgk_uses_shortcut_switch.return_value = False
    p._layout_manager.sgk_get_current_layout.return_value = "ru"
    assert await p._sgk_switch_layout("ru") == "ru"
    p._layout_manager.sgk_switch_to.assert_called_once_with("ru")
    assert "super+space" not in _sent_keys(p)


@pytest.mark.asyncio
async def test_legacy_backend_falls_back_to_shortcut() -> None:
    p = _make_processor()
    p._layout_manager.sgk_uses_shortcut_switch.return_value = False
    p._layout_manager.sgk_layout_matches.side_effect = [False, True]
    await p._sgk_switch_layout("ru")
    assert _sent_keys(p).count("super+space") == 1


@pytest.mark.asyncio
async def test_order_paste_then_switch_then_restore() -> None:
    p = _make_processor(get_returns=["orig", "ghbdtn"], converted="привет")
    order: list[str] = []
    paste = p._clipboard.sgk_paste_text.side_effect
    p._clipboard.sgk_paste_text.side_effect = None

    async def _paste(text, combo):
        order.append("paste")
        return True

    async def _press(combo, count):
        order.append("switch")
        await p._gnome.press(combo, count)

    original_set = p._clipboard.sgk_set.side_effect

    async def _set(text, confirm=False):
        if text == "orig":
            order.append("restore")
        return await original_set(text, confirm)

    assert paste is None
    p._clipboard.sgk_paste_text.side_effect = _paste
    p._clipboard.sgk_send_key_repeat.side_effect = _press
    p._clipboard.sgk_set.side_effect = _set
    await p.sgk_process()
    assert order == ["paste", "switch", "restore"]


@pytest.mark.asyncio
async def test_repeat_press_right_after_conversion_only_fixes_layout() -> None:
    p = _make_processor(get_returns=["orig", "ghbdtn", "orig", MARKER, MARKER], converted="привет")
    await p.sgk_process()
    p._gnome.inmem = ["en", "ru"]
    await p.sgk_process()
    assert "ctrl+shift+Left" not in _sent_keys(p)
    assert p._clipboard.sgk_paste_text.call_count == 1
    assert p._gnome.window == "ru"
    assert _set_values(p)[-1] == "orig"
    assert p._sgk_last_target is None


@pytest.mark.asyncio
async def test_repeat_press_with_layout_already_target_falls_back_to_word() -> None:
    p = _make_processor(
        get_returns=["orig", "ghbdtn", "orig", MARKER, MARKER, "word"], converted="привет"
    )
    await p.sgk_process()
    assert p._gnome.window == "ru"
    await p.sgk_process()
    assert "ctrl+shift+Left" in _sent_keys(p)
    assert p._clipboard.sgk_paste_text.call_count == 2


@pytest.mark.asyncio
async def test_repeat_press_without_ibus_keeps_layout_only_path() -> None:
    gnome = _FakeGnome(window="en", active=["en", "ru"], ibus=False)
    p = _make_processor(
        get_returns=["orig", "ghbdtn", "orig", MARKER, MARKER, "word"],
        converted="привет",
        gnome=gnome,
    )
    await p.sgk_process()
    await p.sgk_process()
    assert "ctrl+shift+Left" not in _sent_keys(p)
    assert p._clipboard.sgk_paste_text.call_count == 1


@pytest.mark.asyncio
async def test_repeat_press_after_window_falls_back_to_word() -> None:
    p = _make_processor(
        get_returns=["orig", "ghbdtn", "orig", MARKER, MARKER, "word"], converted="привет"
    )
    await p.sgk_process()
    p._sgk_last_target = ("ru", p._sgk_last_target[1] - 60)
    await p.sgk_process()
    assert "ctrl+shift+Left" in _sent_keys(p)
    assert p._clipboard.sgk_paste_text.call_count == 2


@pytest.mark.asyncio
async def test_last_word_hotkey_ignores_repeat_window() -> None:
    p = _make_processor(get_returns=["orig", "ghbdtn", "orig", "word"], converted="привет")
    await p.sgk_process()
    await p.sgk_process(mode="convert_last_word")
    assert "ctrl+shift+Left" in _sent_keys(p)
    assert p._clipboard.sgk_paste_text.call_count == 2


@pytest.mark.asyncio
async def test_failed_word_fallback_collapses_selection() -> None:
    p = _make_processor(get_returns=["orig", MARKER, MARKER, MARKER])
    await p.sgk_process()
    keys = _sent_keys(p)
    assert keys[-1] == "right"
    assert keys.index("ctrl+shift+Left") < keys.index("right")
    p._clipboard.sgk_paste_text.assert_not_called()
    assert _set_values(p)[-1] == "orig"


@pytest.mark.asyncio
async def test_no_selection_without_fallback_sends_no_right() -> None:
    p = _make_processor(get_returns=["orig", MARKER, MARKER], fallback_to_word=False)
    await p.sgk_process()
    assert "right" not in _sent_keys(p)


@pytest.mark.asyncio
async def test_unexpected_error_restores_clipboard_and_resets_busy() -> None:
    p = _make_processor(get_returns=["USER_SECRET", "qwe", "orig", "ghbdtn"], converted="X")
    p._mapper.sgk_convert.side_effect = [TypeError("bad map"), "привет"]
    await p.sgk_process()
    assert _set_values(p)[-1] == "USER_SECRET"
    assert p._busy is False
    await p.sgk_process()
    p._clipboard.sgk_paste_text.assert_called_once_with("привет", "ctrl+v")


@pytest.mark.asyncio
async def test_error_after_restore_does_not_restore_twice() -> None:
    p = _make_processor(get_returns=["orig", "ghbdtn"], converted="привет")
    p._detector.sgk_get_active_window_info.side_effect = [RuntimeError("x")]
    p._sgk_sensitive = lambda: False
    await p.sgk_process()
    assert _set_values(p).count("orig") == 1


@pytest.mark.asyncio
async def test_terminal_error_restores_clipboard() -> None:
    p = _make_processor(get_returns=["orig"], primary="руддщ", detected_layout="ru",
                        converted="hello")
    p._clipboard.sgk_paste_text.side_effect = RuntimeError("boom")
    await p.sgk_process(mode="convert_terminal")
    assert _set_values(p)[-1] == "orig"


@pytest.mark.asyncio
async def test_non_text_clipboard_snapshot_is_restored() -> None:
    from sgk_wordwrap.input.clipboard import SgkClipboardBlob

    blob = SgkClipboardBlob("image/png", b"\x89PNG")
    p = _make_processor(get_returns=[None, "text"], converted="CONV", snapshot=blob)
    await p.sgk_process()
    p._clipboard.sgk_set_blob.assert_called_once_with(blob)
    p._clipboard.sgk_clear.assert_not_called()


@pytest.mark.asyncio
async def test_failed_blob_restore_clears_clipboard() -> None:
    from sgk_wordwrap.input.clipboard import SgkClipboardBlob

    blob = SgkClipboardBlob("image/png", b"\x89PNG")
    p = _make_processor(get_returns=[None, "text"], converted="CONV", snapshot=blob)
    p._clipboard.sgk_set_blob.return_value = False
    await p.sgk_process()
    p._clipboard.sgk_clear.assert_called_once()


@pytest.mark.asyncio
async def test_text_clipboard_does_not_take_snapshot() -> None:
    p = _make_processor(get_returns=["orig", "text"], converted="CONV")
    await p.sgk_process()
    p._clipboard.sgk_snapshot_non_text.assert_not_called()


@pytest.mark.asyncio
async def test_three_layouts_target_skips_layout_without_map() -> None:
    p = _make_processor(
        get_returns=["orig", "ghbdtn"], converted="привет", active_layouts=["en", "de", "ru"]
    )
    p._mapper.sgk_has_map.side_effect = lambda a, b: (a, b) == ("en", "ru")
    await p.sgk_process()
    p._mapper.sgk_convert.assert_called_once_with("ghbdtn", "en", "ru")


@pytest.mark.asyncio
async def test_three_layouts_target_is_first_other_with_map() -> None:
    p = _make_processor(
        get_returns=["orig", "ghbdtn"], converted="привет", active_layouts=["en", "ru", "uk"]
    )
    await p.sgk_process()
    p._mapper.sgk_convert.assert_called_once_with("ghbdtn", "en", "ru")


@pytest.mark.asyncio
async def test_single_active_layout_uses_next_layout() -> None:
    p = _make_processor(get_returns=["orig", "ghbdtn"], active_layouts=["en"], next_layout="en")
    p._mapper.sgk_has_map.return_value = False
    await p.sgk_process()
    p._clipboard.sgk_paste_text.assert_not_called()


@pytest.mark.asyncio
async def test_terminal_word_erase_counts_tokens_not_spaces() -> None:
    p = _make_processor(
        get_returns=["orig"], primary="ghbdtn  vbh ", detected_layout="en",
        converted="привет мир", terminal_erase="word",
    )
    await p.sgk_process(mode="convert_terminal")
    assert _sent_keys(p).count("ctrl+w") == 2


@pytest.mark.asyncio
async def test_terminal_word_erase_single_spaced() -> None:
    p = _make_processor(
        get_returns=["orig"], primary="a b\tc", detected_layout="en",
        converted="ф и с", terminal_erase="word",
    )
    await p.sgk_process(mode="convert_terminal")
    assert _sent_keys(p).count("ctrl+w") == 3


@pytest.mark.asyncio
async def test_terminal_backspace_too_long_aborts_and_restores() -> None:
    p = _make_processor(
        get_returns=["orig"], primary="g" * 300, detected_layout="en",
        converted="п" * 300, terminal_erase="backspace",
    )
    await p.sgk_process(mode="convert_terminal")
    p._clipboard.sgk_backspace.assert_not_called()
    p._clipboard.sgk_paste_text.assert_not_called()
    assert _set_values(p)[-1] == "orig"


@pytest.mark.asyncio
async def test_terminal_sensitive_context_skipped() -> None:
    p = _make_processor(primary="ghbdtn", sensitive=True)
    await p.sgk_process(mode="convert_terminal")
    p._clipboard.sgk_get_primary.assert_not_called()


@pytest.mark.asyncio
async def test_terminal_success_restores_clipboard() -> None:
    p = _make_processor(get_returns=["orig"], primary="ghbdtn", converted="привет")
    await p.sgk_process(mode="convert_terminal")
    assert _set_values(p)[-1] == "orig"


@pytest.mark.asyncio
async def test_unknown_mode_runs_selection_flow() -> None:
    p = _make_processor(get_returns=["orig", "ghbdtn"], converted="привет")
    await p.sgk_process(mode="something")
    p._clipboard.sgk_paste_text.assert_called_once_with("привет", "ctrl+v")


@pytest.mark.asyncio
async def test_no_text_acquired_does_not_paste_and_restores() -> None:
    p = _make_processor(get_returns=["orig", MARKER, MARKER, MARKER])
    await p.sgk_process()
    p._clipboard.sgk_paste_text.assert_not_called()
    assert _set_values(p)[-1] == "orig"
