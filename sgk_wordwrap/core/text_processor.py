"""Main text conversion logic.

Scenario A — text is selected:
  1. Save clipboard → Ctrl+C → read selection → convert → Ctrl+V → restore clipboard

Scenario B — no selection:
  1. Ctrl+Shift+Left to select last word → then scenario A

Safety checks:
  - Non-text clipboard content → skip
  - Password field (AT-SPI / blacklist) → skip
  - Text too long (>10k chars) → skip
  - Any exception → log, do NOT crash
"""

from __future__ import annotations

import asyncio
import time

from sgk_wordwrap.core.hotkey_manager import SgkHotkeyManager
from sgk_wordwrap.core.layout_manager import SgkLayoutManager
from sgk_wordwrap.input.clipboard import SgkClipboard
from sgk_wordwrap.layouts.detector import SgkFieldDetector
from sgk_wordwrap.layouts.mapper import SgkLayoutMapper
from sgk_wordwrap.utils.logger import sgk_get_logger

_logger = sgk_get_logger(__name__)


class SgkTextProcessor:
    """Orchestrates the full convert-and-retype flow."""

    def __init__(
        self,
        clipboard: SgkClipboard,
        layout_manager: SgkLayoutManager,
        mapper: SgkLayoutMapper,
        detector: SgkFieldDetector,
        hotkey_manager: SgkHotkeyManager | None = None,
        max_text_length: int = 10000,
        fallback_to_word: bool = True,
    ) -> None:
        self._clipboard = clipboard
        self._layout_manager = layout_manager
        self._mapper = mapper
        self._detector = detector
        self._hotkey_manager = hotkey_manager
        self._max_length = max_text_length
        self._fallback_to_word = fallback_to_word

    async def sgk_process(self) -> None:
        """Entry point — called when hotkey fires."""
        t_start = time.monotonic()
        try:
            # Short sleep to allow user to release physical keys (avoid modifier pollution)
            await asyncio.sleep(0.15)
            await self._sgk_do_process()
        except Exception as exc:
            _logger.error("sgk_process_unexpected_error", extra={"error": str(exc)})
        finally:
            latency_ms = round((time.monotonic() - t_start) * 1000)
            _logger.debug("sgk_process_done", extra={"latency_ms": latency_ms})

    async def _sgk_do_process(self) -> None:
        # 1. Check sensitive context (password field / blacklisted app)
        process_name, window_class, window_title = (
            self._detector.sgk_get_active_window_info()
        )
        if self._detector.sgk_is_sensitive_context(process_name, window_class, window_title):
            _logger.info(
                "sgk_skipped_sensitive",
                extra={"process": process_name, "class": window_class},
            )
            return

        # 2. Save clipboard before we touch it
        saved_clipboard = await self._clipboard.sgk_get()

        try:
            text = await self._sgk_acquire_text(saved_clipboard)
        except Exception as exc:
            _logger.warning("sgk_acquire_text_failed", extra={"error": str(exc)})
            return

        if not text:
            _logger.debug("sgk_no_text_acquired")
            return

        if not SgkClipboard.sgk_is_text_safe(text, self._max_length):
            _logger.debug("sgk_text_unsafe", extra={"len": len(text)})
            await self._sgk_restore(saved_clipboard)
            return

        # 3. Determine conversion direction
        layout_before = self._layout_manager.sgk_get_current_layout()
        layout_after = self._layout_manager.sgk_get_next_layout()

        if not self._mapper.sgk_has_map(layout_before, layout_after):
            _logger.warning(
                "sgk_no_map",
                extra={"from": layout_before, "to": layout_after},
            )
            await self._sgk_restore(saved_clipboard)
            return

        # 4. Convert
        converted = self._mapper.sgk_convert(text, layout_before, layout_after)
        if converted == text:
            _logger.debug("sgk_no_change_after_convert")
            await self._sgk_restore(saved_clipboard)
            return

        # 5. Replace text: type converted text (replaces active selection)
        await self._sgk_replace_text(converted)

        # 6. Switch layout
        self._layout_manager.sgk_switch_to_next()

        # 7. Restore original clipboard
        await self._sgk_restore(saved_clipboard)

        _logger.info(
            "sgk_convert",
            extra={
                "app": process_name or "unknown",
                "window_class": window_class or "unknown",
                "layout_before": layout_before,
                "layout_after": layout_after,
                "char_count": len(text),
            },
        )

    async def _sgk_acquire_text(self, saved_clipboard: str | None) -> str | None:
        """Attempt Scenario A (selection), fall back to Scenario B (word).

        Wayland: read PRIMARY selection directly — no Ctrl+C needed.
        X11: PRIMARY selection is also used (mouse-selected text).
        """
        # --- Scenario A: get selected text ---
        # Try PRIMARY first (common for Linux)
        selected = await self._clipboard.sgk_get_primary()
        if selected and selected.strip():
            _logger.debug("sgk_acquired_via_primary", extra={"len": len(selected)})
            return selected

        # If PRIMARY is empty, try Scenario B: no selection — recover last word
        if not self._fallback_to_word:
            return None

        # 1. Try buffer-based recovery (from evdev listener)
        if self._hotkey_manager:
            word = self._hotkey_manager.sgk_get_last_word()
            if word:
                _logger.debug("sgk_acquired_via_buffer", extra={"word": word})
                # If we use buffer recovery, we MUST backspace over the typed word
                for _ in range(len(word)):
                    await self._clipboard.sgk_send_key("backspace")
                    await asyncio.sleep(0.01)
                
                # We also need to clear the buffer so it's not reused
                self._hotkey_manager.sgk_clear_buffer()
                return word

        _logger.debug("sgk_falling_back_to_word_selection")
        # 2. Last resort: Select word (Ctrl+Shift+Left)
        await self._clipboard.sgk_send_key("ctrl+shift+Left")
        await asyncio.sleep(0.2)  # Wait for selection to happen

        # 3. Read what was just selected (should now be in PRIMARY)
        word = await self._clipboard.sgk_get_primary()
        if word and word.strip():
            _logger.debug("sgk_acquired_via_word_selection", extra={"len": len(word)})
            return word

        return None

    async def _sgk_replace_text(self, converted: str) -> None:
        """Type the converted text, replacing any active selection.

        Delay lets the hotkey keys physically release before injection,
        so modifiers (Ctrl, Alt) don't interfere with the typed text.
        """
        await asyncio.sleep(0.25)
        await self._clipboard.sgk_type_text(converted)

    async def _sgk_restore(self, saved: str | None) -> None:
        """Restore clipboard to saved state."""
        if saved is not None:
            await asyncio.sleep(0.05)
            await self._clipboard.sgk_set(saved)
