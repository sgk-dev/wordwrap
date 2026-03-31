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
        max_text_length: int = 10000,
        fallback_to_word: bool = True,
    ) -> None:
        self._clipboard = clipboard
        self._layout_manager = layout_manager
        self._mapper = mapper
        self._detector = detector
        self._max_length = max_text_length
        self._fallback_to_word = fallback_to_word

    async def sgk_process(self) -> None:
        """Entry point — called when hotkey fires."""
        t_start = time.monotonic()
        try:
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

        # 5. Replace text: set clipboard → Ctrl+V
        ok = await self._clipboard.sgk_set(converted)
        if not ok:
            _logger.warning("sgk_clipboard_write_failed")
            await self._sgk_restore(saved_clipboard)
            return

        await self._clipboard.sgk_send_key("ctrl+v")

        # 6. Switch layout
        self._layout_manager.sgk_switch_to_next()

        # 7. Restore original clipboard
        await self._sgk_restore(saved_clipboard)

        _logger.info(
            "sgk_convert",
            extra={
                "process": process_name or "unknown",
                "window_class": window_class or "unknown",
                "layout_before": layout_before,
                "layout_after": layout_after,
                "char_count": len(text),
            },
        )

    async def _sgk_acquire_text(self, saved_clipboard: str | None) -> str | None:
        """Attempt Scenario A (selection), fall back to Scenario B (word)."""
        # --- Scenario A: try to get selected text via Ctrl+C ---
        await self._clipboard.sgk_send_key("ctrl+c")
        # Give app time to copy
        await asyncio.sleep(0.1)
        new_clipboard = await self._clipboard.sgk_get()

        if new_clipboard and new_clipboard != saved_clipboard and new_clipboard.strip():
            return new_clipboard

        # --- Scenario B: no selection — select last word ---
        if not self._fallback_to_word:
            return None

        await self._clipboard.sgk_send_key("ctrl+shift+Left")
        await asyncio.sleep(0.08)
        await self._clipboard.sgk_send_key("ctrl+c")
        await asyncio.sleep(0.1)

        word_clipboard = await self._clipboard.sgk_get()
        if word_clipboard and word_clipboard != saved_clipboard and word_clipboard.strip():
            return word_clipboard

        return None

    async def _sgk_restore(self, saved: str | None) -> None:
        """Restore clipboard to saved state."""
        if saved is not None:
            await asyncio.sleep(0.05)
            await self._clipboard.sgk_set(saved)
