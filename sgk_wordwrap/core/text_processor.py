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
     terminals) - this replaces the active selection.
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
        copy_settle_ms: int = 120,
        layout_settle_ms: int = 60,
        terminal_paste_combo: str = "ctrl+shift+v",
        terminal_max_backspaces: int = 200,
    ) -> None:
        self._clipboard = clipboard
        self._layout_manager = layout_manager
        self._mapper = mapper
        self._detector = detector
        self._max_length = max_text_length
        self._fallback_to_word = fallback_to_word
        self._settle = settle_ms / 1000.0
        self._copy_settle = copy_settle_ms / 1000.0
        self._layout_settle = layout_settle_ms / 1000.0
        self._terminal_paste_combo = terminal_paste_combo
        self._terminal_max_backspaces = terminal_max_backspaces

    async def sgk_process(self, mode: str = "convert") -> None:
        """Entry point - called when a convert hotkey fires.

        `mode` is the hotkey name: "convert" (selection), "convert_terminal"
        (erase + paste, for real terminals), "convert_last_word" (no selection
        needed - grabs the last word).
        """
        t_start = time.monotonic()
        try:
            # Let the physical hotkey keys (incl. modifiers) release first.
            await asyncio.sleep(self._settle)
            if mode == "convert_terminal":
                await self._sgk_do_process_terminal()
            else:
                await self._sgk_do_process(last_word=mode == "convert_last_word")
        except Exception as exc:
            _logger.error("sgk_process_unexpected_error", extra={"error": str(exc)})
        finally:
            _logger.debug(
                "sgk_process_done",
                extra={"latency_ms": round((time.monotonic() - t_start) * 1000)},
            )

    def _sgk_sensitive(self) -> bool:
        process_name, window_class, window_title = (
            self._detector.sgk_get_active_window_info()
        )
        if self._detector.sgk_is_sensitive_context(
            process_name, window_class, window_title
        ):
            _logger.info(
                "sgk_skipped_sensitive",
                extra={"proc": process_name, "win_class": window_class},
            )
            return True
        return False

    async def _sgk_do_process(self, last_word: bool = False) -> None:
        if self._sgk_sensitive():
            return
        terminal = False

        saved_clipboard = await self._clipboard.sgk_get()

        text = await self._sgk_acquire_text(saved_clipboard, force_word=last_word)
        if not text:
            _logger.debug("sgk_no_text_acquired")
            await self._sgk_restore(saved_clipboard)
            return

        if not SgkClipboard.sgk_is_text_safe(text, self._max_length):
            _logger.debug("sgk_text_unsafe", extra={"len": len(text)})
            await self._sgk_restore(saved_clipboard)
            return

        layout_before, layout_after = self._sgk_pick_direction(text)

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
        await self._sgk_switch_layout(layout_after)
        await self._sgk_restore(saved_clipboard)
        self._sgk_log_convert(layout_before, layout_after, len(text), terminal=False)

    def _sgk_log_convert(
        self, layout_before: str, layout_after: str, char_count: int, terminal: bool
    ) -> None:
        proc, win_class, _ = self._detector.sgk_get_active_window_info()
        _logger.info(
            "sgk_convert",
            extra={
                "app": proc or "unknown",
                "window_class": win_class or "unknown",
                "layout_before": layout_before,
                "layout_after": layout_after,
                "char_count": char_count,
                "terminal": terminal,
            },
        )

    async def _sgk_do_process_terminal(self) -> None:
        """Terminal flow: erase the mistyped text and paste the fixed text.

        Real terminals have no editable selection and no 'replace on paste', and
        Ctrl+Insert / Ctrl+Shift+Left mean different things per terminal. So:
        take the text from the mouse selection (PRIMARY), Backspace over it, then
        paste the converted text with the configured terminal paste shortcut.

        Assumes the mistyped text is at the end of the current input line (you
        typed it, noticed, selected it, hit the hotkey).
        """
        if self._sgk_sensitive():
            return

        saved_clipboard = await self._clipboard.sgk_get()

        text = await self._clipboard.sgk_get_primary()
        if not text or not text.strip():
            _logger.info("sgk_terminal_no_selection")
            await self._sgk_restore(saved_clipboard)
            return

        if not SgkClipboard.sgk_is_text_safe(text, self._max_length):
            _logger.debug("sgk_text_unsafe", extra={"len": len(text)})
            await self._sgk_restore(saved_clipboard)
            return

        layout_before, layout_after = self._sgk_pick_direction(text)
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

        if len(text) > self._terminal_max_backspaces:
            _logger.warning(
                "sgk_terminal_too_long",
                extra={"len": len(text), "max": self._terminal_max_backspaces},
            )
            await self._sgk_restore(saved_clipboard)
            return

        await self._clipboard.sgk_backspace(len(text))
        await self._clipboard.sgk_paste_text(converted, self._terminal_paste_combo)
        await self._sgk_switch_layout(layout_after)
        await self._sgk_restore(saved_clipboard)
        self._sgk_log_convert(layout_before, layout_after, len(text), terminal=True)

    def _sgk_pick_direction(self, text: str) -> tuple[str, str]:
        """Decide which way to convert.

        Direction depends on the *script the text is currently in*, not on which
        layout is active (the wrong layout is usually still active, and for
        already-typed text that tells us nothing). Detect the source layout from
        the characters; fall back to current -> other only if undetectable.
        """
        active = self._layout_manager.sgk_get_active_layouts() or ["en", "ru"]
        detected = self._mapper.sgk_detect_likely_layout(text, active)
        source = detected or self._layout_manager.sgk_get_current_layout()
        others = [lay for lay in active if lay != source]
        target = others[0] if others else self._layout_manager.sgk_get_next_layout()
        _logger.debug(
            "sgk_direction",
            extra={"detected": detected, "source": source, "target": target},
        )
        return source, target

    async def _sgk_acquire_text(
        self, saved_clipboard: str | None, force_word: bool = False
    ) -> str | None:
        """Get the text to convert.

        PRIMARY persists the last mouse selection forever on Linux, so it cannot
        tell us whether something is selected *now*. Instead we force the current
        selection into the CLIPBOARD with a copy shortcut and see whether it
        changed. If not, nothing is selected → (optionally) select the last word
        ourselves.

        `force_word=True` (the "convert last word" hotkey) skips the "is
        something already selected?" check and always selects the last word.

        The copy shortcut is Ctrl+Insert, not Ctrl+C: in a terminal Ctrl+C is
        SIGINT and would kill the foreground program.
        """
        if not force_word:
            text = await self._sgk_copy_selection()
            if text and text.strip() and text != saved_clipboard:
                _logger.debug("sgk_acquired_via_selection", extra={"len": len(text)})
                return text
            if not self._fallback_to_word:
                return None

        await self._clipboard.sgk_send_key("ctrl+shift+Left")
        await asyncio.sleep(0.12)
        text = await self._sgk_copy_selection()
        if text and text.strip() and text != saved_clipboard:
            _logger.debug("sgk_acquired_via_word_selection", extra={"len": len(text)})
            return text
        return None

    async def _sgk_copy_selection(self) -> str | None:
        """Copy the current selection into CLIPBOARD (Ctrl+Insert) and read it."""
        await self._clipboard.sgk_send_key("ctrl+insert")
        await asyncio.sleep(self._copy_settle)
        return await self._clipboard.sgk_get()

    async def _sgk_switch_layout(self, target: str) -> None:
        """Switch the system layout to `target`, with a uinput fallback.

        `gsettings set ... current <idx>` does not always take effect in a live
        GNOME session, so if the layout has not changed after a short settle we
        press the GNOME 'switch input source' shortcut (default Super+Space)
        until it matches or we run out of tries.
        """
        self._layout_manager.sgk_switch_to(target)
        await asyncio.sleep(self._layout_settle)
        if self._layout_manager.sgk_layout_matches(target):
            return

        shortcut = self._layout_manager.sgk_get_switch_shortcut()
        tries = max(1, len(self._layout_manager.sgk_get_active_layouts()))
        for _ in range(tries):
            await self._clipboard.sgk_send_key(shortcut)
            await asyncio.sleep(0.08)
            if self._layout_manager.sgk_layout_matches(target):
                break
        _logger.debug(
            "sgk_layout_after_switch",
            extra={
                "want": target,
                "now": self._layout_manager.sgk_get_current_layout(),
                "used_shortcut": shortcut,
            },
        )

    async def _sgk_restore(self, saved: str | None) -> None:
        if saved is not None:
            await asyncio.sleep(0.05)
            await self._clipboard.sgk_set(saved)
