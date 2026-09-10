"""Main text conversion flow.

On hotkey:
  1. Skip if the focused context looks sensitive (password field / blacklist).
  2. Save the user's clipboard.
  3. Acquire text: PRIMARY selection; if empty and the fallback is enabled,
     select the last word (Ctrl+Shift+Left) and read PRIMARY again.
  4. Bail out on unsafe text (empty / too long).
  5. Direction = current layout → the other layout; bail if there is no map.
  6. Convert; bail if nothing changes.
  7. Paste the converted text (clipboard swap + Ctrl+V, or Ctrl+Shift+V for
     terminals) — this replaces the active selection.
  8. Switch the system layout to the target.
  9. Restore the user's clipboard.

Any exception is logged; the daemon never crashes. Text content is never logged.
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
    """Orchestrates the convert-and-retype flow."""

    def __init__(
        self,
        clipboard: SgkClipboard,
        layout_manager: SgkLayoutManager,
        mapper: SgkLayoutMapper,
        detector: SgkFieldDetector,
        max_text_length: int = 10000,
        fallback_to_word: bool = True,
        settle_ms: int = 150,
    ) -> None:
        self._clipboard = clipboard
        self._layout_manager = layout_manager
        self._mapper = mapper
        self._detector = detector
        self._max_length = max_text_length
        self._fallback_to_word = fallback_to_word
        self._settle = settle_ms / 1000.0

    async def sgk_process(self, terminal: bool = False) -> None:
        """Entry point — called when a convert hotkey fires."""
        t_start = time.monotonic()
        try:
            # Let the physical hotkey keys (incl. modifiers) release first.
            await asyncio.sleep(self._settle)
            await self._sgk_do_process(terminal)
        except Exception as exc:
            _logger.error("sgk_process_unexpected_error", extra={"error": str(exc)})
        finally:
            _logger.debug(
                "sgk_process_done",
                extra={"latency_ms": round((time.monotonic() - t_start) * 1000)},
            )

    async def _sgk_do_process(self, terminal: bool) -> None:
        process_name, window_class, window_title = (
            self._detector.sgk_get_active_window_info()
        )
        if self._detector.sgk_is_sensitive_context(
            process_name, window_class, window_title
        ):
            _logger.info(
                "sgk_skipped_sensitive",
                extra={"process": process_name, "class": window_class},
            )
            return

        saved_clipboard = await self._clipboard.sgk_get()

        text = await self._sgk_acquire_text()
        if not text:
            _logger.debug("sgk_no_text_acquired")
            await self._sgk_restore(saved_clipboard)
            return

        if not SgkClipboard.sgk_is_text_safe(text, self._max_length):
            _logger.debug("sgk_text_unsafe", extra={"len": len(text)})
            await self._sgk_restore(saved_clipboard)
            return

        layout_before = self._layout_manager.sgk_get_current_layout()
        layout_after = self._layout_manager.sgk_get_next_layout()

        if not self._mapper.sgk_has_map(layout_before, layout_after):
            _logger.warning(
                "sgk_no_map", extra={"from": layout_before, "to": layout_after}
            )
            await self._sgk_restore(saved_clipboard)
            return

        converted = self._mapper.sgk_convert(text, layout_before, layout_after)
        if converted == text:
            _logger.debug("sgk_no_change_after_convert")
            await self._sgk_restore(saved_clipboard)
            return

        await self._clipboard.sgk_type_text(converted, terminal=terminal)
        self._layout_manager.sgk_switch_to(layout_after)
        await self._sgk_restore(saved_clipboard)

        _logger.info(
            "sgk_convert",
            extra={
                "app": process_name or "unknown",
                "window_class": window_class or "unknown",
                "layout_before": layout_before,
                "layout_after": layout_after,
                "char_count": len(text),
                "terminal": terminal,
            },
        )

    async def _sgk_acquire_text(self) -> str | None:
        """PRIMARY selection, or (fallback) select the last word and re-read it."""
        selected = await self._clipboard.sgk_get_primary()
        if selected and selected.strip():
            _logger.debug("sgk_acquired_via_primary", extra={"len": len(selected)})
            return selected

        if not self._fallback_to_word:
            return None

        await self._clipboard.sgk_send_key("ctrl+shift+Left")
        await asyncio.sleep(0.12)
        word = await self._clipboard.sgk_get_primary()
        if word and word.strip():
            _logger.debug("sgk_acquired_via_word_selection", extra={"len": len(word)})
            return word
        return None

    async def _sgk_restore(self, saved: str | None) -> None:
        if saved is not None:
            await asyncio.sleep(0.05)
            await self._clipboard.sgk_set(saved)
