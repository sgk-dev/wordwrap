"""Unit tests for SgkTextProcessor (mocked dependencies).

Text acquisition model: the processor calls clipboard.sgk_get() once to save the
user's clipboard, then Ctrl+Insert's the selection and reads sgk_get() again to
see whether it changed. So `get_returns` is the full sgk_get() call sequence:
[saved, after_first_copy, (after_word_select_copy)]. The terminal flow instead
reads clipboard.sgk_get_primary() (the `primary` kwarg).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from sgk_wordwrap.core.layout_manager import SgkLayoutManager
from sgk_wordwrap.core.text_processor import SgkTextProcessor
from sgk_wordwrap.input.clipboard import SgkClipboard
from sgk_wordwrap.layouts.detector import SgkFieldDetector
from sgk_wordwrap.layouts.mapper import SgkLayoutMapper


def _make_processor(
    get_returns: list[str | None] | None = None,
    current_layout: str = "en",
    next_layout: str = "ru",
    detected_layout: str | None = "en",
    active_layouts: list[str] | None = None,
    sensitive: bool = False,
    converted: str = "CONVERTED",
    fallback_to_word: bool = True,
    primary: str | None = None,
    terminal_erase: str = "line",
) -> SgkTextProcessor:
    clipboard = MagicMock(spec=SgkClipboard)
    clipboard.sgk_get = AsyncMock(side_effect=(get_returns or [None] * 10))
    clipboard.sgk_get_primary = AsyncMock(return_value=primary)
    clipboard.sgk_set = AsyncMock(return_value=True)
    clipboard.sgk_type_text = AsyncMock(return_value=True)
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
        settle_ms=0,
        copy_settle_ms=0,
        layout_settle_ms=0,
        terminal_settle_ms=0,
        terminal_erase=terminal_erase,
    )


@pytest.mark.asyncio
async def test_selected_text_converted_and_pasted() -> None:
    p = _make_processor(get_returns=["orig", "ghbdtn"], converted="привет")
    await p.sgk_process()
    p._clipboard.sgk_send_key.assert_any_call("ctrl+insert")
    p._clipboard.sgk_type_text.assert_called_once_with("привет", terminal=False)
    p._layout_manager.sgk_switch_to.assert_called_once_with("ru")


@pytest.mark.asyncio
async def test_layout_switch_uinput_fallback_when_gsettings_ineffective() -> None:
    p = _make_processor(get_returns=["orig", "ghbdtn"], converted="привет")
    p._layout_manager.sgk_layout_matches.return_value = False
    await p.sgk_process()
    p._layout_manager.sgk_switch_to.assert_called_once_with("ru")
    # gsettings did not stick -> pressed the GNOME switch shortcut as fallback
    calls = [c.args[0] for c in p._clipboard.sgk_send_key.call_args_list]
    assert "super+space" in calls


@pytest.mark.asyncio
async def test_terminal_mode_clears_line_then_pastes() -> None:
    p = _make_processor(
        get_returns=["orig"], primary="руддщ", detected_layout="ru", converted="hello"
    )
    await p.sgk_process(mode="convert_terminal")
    calls = [c.args[0] for c in p._clipboard.sgk_send_key.call_args_list]
    assert calls == ["ctrl+a", "ctrl+k"]
    p._clipboard.sgk_paste_text.assert_called_once_with("hello", "ctrl+shift+v")
    p._clipboard.sgk_type_text.assert_not_called()
    p._layout_manager.sgk_switch_to.assert_called_once_with("en")


@pytest.mark.asyncio
async def test_terminal_mode_strips_selection_whitespace() -> None:
    p = _make_processor(
        get_returns=["orig"], primary="  руддщ \n", detected_layout="ru",
        converted="hello", terminal_erase="backspace",
    )
    await p.sgk_process(mode="convert_terminal")
    # trailing "\n" was inside strip(), "  руддщ " -> "руддщ" (5), not 8
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
async def test_last_word_mode_forces_word_selection() -> None:
    # No pre-existing selection: first sgk_get() is the save, then the word-select
    # copy returns the word.
    p = _make_processor(get_returns=["orig", "wordtext"], converted="ПЕРЕВОД")
    await p.sgk_process(mode="convert_last_word")
    calls = [c.args[0] for c in p._clipboard.sgk_send_key.call_args_list]
    assert "ctrl+shift+Left" in calls
    # it must NOT try to read an existing selection first
    assert calls.count("ctrl+insert") == 1
    p._clipboard.sgk_type_text.assert_called_once_with("ПЕРЕВОД", terminal=False)


@pytest.mark.asyncio
async def test_direction_follows_detected_source_not_active_layout() -> None:
    # Text is Latin (detected 'en') even though the RU layout is currently active.
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
    # first Ctrl+C leaves the clipboard unchanged (== saved) → word-select path
    p = _make_processor(get_returns=["orig", "orig", "wordtext"], converted="WT_RU")
    await p.sgk_process()
    calls = [c.args[0] for c in p._clipboard.sgk_send_key.call_args_list]
    assert "ctrl+shift+Left" in calls
    p._clipboard.sgk_type_text.assert_called_once_with("WT_RU", terminal=False)


@pytest.mark.asyncio
async def test_no_selection_no_fallback_is_noop() -> None:
    p = _make_processor(get_returns=["orig", "orig"], fallback_to_word=False)
    await p.sgk_process()
    p._clipboard.sgk_type_text.assert_not_called()
    p._layout_manager.sgk_switch_to.assert_not_called()


@pytest.mark.asyncio
async def test_sensitive_context_skipped_without_touching_clipboard() -> None:
    p = _make_processor(sensitive=True)
    await p.sgk_process()
    p._clipboard.sgk_get.assert_not_called()
    p._clipboard.sgk_send_key.assert_not_called()
    p._clipboard.sgk_type_text.assert_not_called()
    p._layout_manager.sgk_switch_to.assert_not_called()


@pytest.mark.asyncio
async def test_no_text_acquired_skipped() -> None:
    p = _make_processor(get_returns=["orig", "orig", "orig"])
    await p.sgk_process()
    p._layout_manager.sgk_switch_to.assert_not_called()


@pytest.mark.asyncio
async def test_text_too_long_skipped_and_clipboard_restored() -> None:
    p = _make_processor(get_returns=["orig", "a" * 20000])
    await p.sgk_process()
    p._clipboard.sgk_type_text.assert_not_called()
    p._layout_manager.sgk_switch_to.assert_not_called()
    p._clipboard.sgk_set.assert_called_once_with("orig")


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
    p._clipboard.sgk_type_text.assert_not_called()
    p._layout_manager.sgk_switch_to.assert_not_called()
    p._clipboard.sgk_set.assert_called_once_with("orig")


@pytest.mark.asyncio
async def test_clipboard_restored_after_successful_conversion() -> None:
    p = _make_processor(get_returns=["MY_SAVED", "text"], converted="CONV")
    await p.sgk_process()
    assert p._clipboard.sgk_set.call_args_list[-1].args[0] == "MY_SAVED"
