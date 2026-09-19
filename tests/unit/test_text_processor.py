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
) -> SgkTextProcessor:
    clipboard = MagicMock(spec=SgkClipboard)
    state = {"last_set": None}
    seq = iter(get_returns or [])

    async def _set(text: str) -> bool:
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

    layout_manager = MagicMock(spec=SgkLayoutManager)
    layout_manager.sgk_get_current_layout.return_value = current_layout
    layout_manager.sgk_get_next_layout.return_value = next_layout
    layout_manager.sgk_get_active_layouts.return_value = active_layouts or ["en", "ru"]
    layout_manager.sgk_switch_to = MagicMock()
    layout_manager.sgk_layout_matches.return_value = True
    layout_manager.sgk_get_switch_shortcut.return_value = "super+space"

    mapper = MagicMock(spec=SgkLayoutMapper)
    mapper.sgk_has_map.return_value = True
    mapper.sgk_convert.return_value = converted
    mapper.sgk_detect_likely_layout.return_value = detected_layout

    detector = MagicMock(spec=SgkFieldDetector)
    detector.sgk_is_sensitive_context.return_value = sensitive
    detector.sgk_get_active_window_info.return_value = ("firefox", "Navigator", "T")

    return SgkTextProcessor(
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
    )


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
    p._layout_manager.sgk_switch_to.assert_called_once_with("ru")


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
async def test_layout_switch_uinput_fallback_when_gsettings_ineffective() -> None:
    p = _make_processor(get_returns=["orig", "ghbdtn"], converted="привет")
    p._layout_manager.sgk_layout_matches.return_value = False
    await p.sgk_process()
    p._layout_manager.sgk_switch_to.assert_called_once_with("ru")
    assert "super+space" in _sent_keys(p)


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
    p._layout_manager.sgk_switch_to.assert_called_once_with("en")


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
    p._layout_manager.sgk_switch_to.assert_called_once_with("ru")


@pytest.mark.asyncio
async def test_reverse_direction_ru_to_en() -> None:
    p = _make_processor(
        get_returns=["orig", "руддщ"],
        detected_layout="ru",
        converted="hello",
    )
    await p.sgk_process()
    p._mapper.sgk_convert.assert_called_once_with("руддщ", "ru", "en")
    p._layout_manager.sgk_switch_to.assert_called_once_with("en")


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
    p = _make_processor(get_returns=["orig", MARKER, "wordtext"], converted="WT_RU")
    await p.sgk_process()
    assert "ctrl+shift+Left" in _sent_keys(p)
    p._clipboard.sgk_paste_text.assert_called_once_with("WT_RU", "ctrl+v")


@pytest.mark.asyncio
async def test_no_selection_no_fallback_is_noop() -> None:
    p = _make_processor(get_returns=["orig", MARKER], fallback_to_word=False)
    await p.sgk_process()
    p._clipboard.sgk_paste_text.assert_not_called()
    p._layout_manager.sgk_switch_to.assert_not_called()
    assert _set_values(p)[-1] == "orig"


@pytest.mark.asyncio
async def test_marker_write_failure_falls_back_to_saved_comparison() -> None:
    p = _make_processor(get_returns=["orig", "orig", "wordtext"], set_ok=False)
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
    p._layout_manager.sgk_switch_to.assert_not_called()


@pytest.mark.asyncio
async def test_no_text_acquired_skipped() -> None:
    p = _make_processor(get_returns=["orig", MARKER, MARKER])
    await p.sgk_process()
    p._layout_manager.sgk_switch_to.assert_not_called()


@pytest.mark.asyncio
async def test_text_too_long_skipped_and_clipboard_restored() -> None:
    p = _make_processor(get_returns=["orig", "a" * 20000])
    await p.sgk_process()
    p._clipboard.sgk_paste_text.assert_not_called()
    p._layout_manager.sgk_switch_to.assert_not_called()
    assert _set_values(p)[-1] == "orig"


@pytest.mark.asyncio
async def test_no_map_skipped() -> None:
    p = _make_processor(get_returns=["orig", "sometext"])
    p._mapper.sgk_has_map.return_value = False
    await p.sgk_process()
    p._layout_manager.sgk_switch_to.assert_not_called()


@pytest.mark.asyncio
async def test_conversion_is_noop_when_nothing_changes() -> None:
    p = _make_processor(get_returns=["orig", "hello"], converted="hello")
    await p.sgk_process()
    p._clipboard.sgk_paste_text.assert_not_called()
    p._layout_manager.sgk_switch_to.assert_not_called()
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
    p = _make_processor(get_returns=["MY_SAVED", MARKER, MARKER], restore_clipboard=False)
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
