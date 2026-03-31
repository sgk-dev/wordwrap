"""Unit tests for SgkTextProcessor (mocked dependencies)."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from sgk_wordwrap.core.text_processor import SgkTextProcessor
from sgk_wordwrap.input.clipboard import SgkClipboard
from sgk_wordwrap.core.layout_manager import SgkLayoutManager
from sgk_wordwrap.layouts.mapper import SgkLayoutMapper
from sgk_wordwrap.layouts.detector import SgkFieldDetector


def _make_processor(
    get_returns: list[str | None],
    current_layout: str = "en",
    next_layout: str = "ru",
    sensitive: bool = False,
    converted: str = "CONVERTED",
) -> SgkTextProcessor:
    clipboard = MagicMock(spec=SgkClipboard)
    clipboard.sgk_get = AsyncMock(side_effect=get_returns)
    clipboard.sgk_set = AsyncMock(return_value=True)
    clipboard.sgk_send_key = AsyncMock()

    layout_manager = MagicMock(spec=SgkLayoutManager)
    layout_manager.sgk_get_current_layout.return_value = current_layout
    layout_manager.sgk_get_next_layout.return_value = next_layout
    layout_manager.sgk_switch_to_next = MagicMock()

    mapper = MagicMock(spec=SgkLayoutMapper)
    mapper.sgk_has_map.return_value = True
    mapper.sgk_convert.return_value = converted

    detector = MagicMock(spec=SgkFieldDetector)
    detector.sgk_is_sensitive_context.return_value = sensitive
    detector.sgk_get_active_window_info.return_value = ("firefox", "Navigator", "Test")

    return SgkTextProcessor(
        clipboard=clipboard,
        layout_manager=layout_manager,
        mapper=mapper,
        detector=detector,
    )


@pytest.mark.asyncio
async def test_scenario_a_selected_text() -> None:
    """Ctrl+C gives different clipboard → convert and paste."""
    processor = _make_processor(
        get_returns=[
            "original_clipboard",   # sgk_get() before Ctrl+C (save)
            "ghbdtn",               # sgk_get() after Ctrl+C (selected text)
            None,                   # sgk_get() in restore
        ],
        converted="привет",
    )
    await processor.sgk_process()
    processor._clipboard.sgk_set.assert_any_call("привет")
    processor._layout_manager.sgk_switch_to_next.assert_called_once()


@pytest.mark.asyncio
async def test_scenario_b_no_selection_fallback() -> None:
    """No selection → Ctrl+Shift+Left selects word → convert."""
    processor = _make_processor(
        get_returns=[
            "saved",   # initial save
            "saved",   # after Ctrl+C — unchanged (no selection)
            "wordtext",  # after Ctrl+Shift+Left + Ctrl+C
            None,        # restore
        ],
        converted="WORDTEXT_RU",
    )
    await processor.sgk_process()
    # Should have called Ctrl+Shift+Left
    calls = [str(c) for c in processor._clipboard.sgk_send_key.call_args_list]
    assert any("ctrl+shift+Left" in c for c in calls)
    processor._clipboard.sgk_set.assert_any_call("WORDTEXT_RU")


@pytest.mark.asyncio
async def test_sensitive_context_skipped() -> None:
    """Password field → skip without touching clipboard."""
    processor = _make_processor(
        get_returns=[],
        sensitive=True,
    )
    await processor.sgk_process()
    processor._clipboard.sgk_set.assert_not_called()
    processor._layout_manager.sgk_switch_to_next.assert_not_called()


@pytest.mark.asyncio
async def test_no_text_acquired_skipped() -> None:
    """Both Ctrl+C and word selection return nothing → no-op."""
    processor = _make_processor(
        get_returns=[
            "saved",
            "saved",   # Ctrl+C: no change
            "saved",   # Ctrl+Shift+Left + Ctrl+C: no change
        ],
    )
    await processor.sgk_process()
    processor._layout_manager.sgk_switch_to_next.assert_not_called()


@pytest.mark.asyncio
async def test_text_too_long_skipped() -> None:
    """Text exceeding max_length → skip conversion."""
    long_text = "a" * 20000
    processor = _make_processor(
        get_returns=[
            "saved",
            long_text,  # Ctrl+C returns very long text
        ],
    )
    processor._max_length = 10000
    await processor.sgk_process()
    processor._layout_manager.sgk_switch_to_next.assert_not_called()


@pytest.mark.asyncio
async def test_no_map_skipped() -> None:
    """No mapping available for the layout pair → skip."""
    processor = _make_processor(
        get_returns=[
            "saved",
            "sometext",
            None,
        ],
    )
    processor._mapper.sgk_has_map.return_value = False
    await processor.sgk_process()
    processor._layout_manager.sgk_switch_to_next.assert_not_called()


@pytest.mark.asyncio
async def test_clipboard_restored_after_conversion() -> None:
    """Original clipboard is restored after paste."""
    processor = _make_processor(
        get_returns=[
            "MY_SAVED_CLIPBOARD",
            "text_to_convert",
            None,
        ],
        converted="CONVERTED_TEXT",
    )
    await processor.sgk_process()
    # Last sgk_set call should restore original clipboard
    last_call = processor._clipboard.sgk_set.call_args_list[-1]
    assert last_call.args[0] == "MY_SAVED_CLIPBOARD"
