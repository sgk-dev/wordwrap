"""Main text conversion flow.

On hotkey:
  1. Skip if the focused context looks sensitive (password field / blacklist).
  2. Save the user's clipboard and put a private marker in it.
  3. Acquire text: Ctrl+Insert copies the selection over the marker; if the
     clipboard still holds the marker nothing was selected, so (optionally)
     select the last word with Ctrl+Shift+Left and copy again.
  4. Bail out on unsafe text (empty / too long).
  5. Direction = script the text is in -> the other layout; bail if no map.
  6. Convert; bail if nothing changes.
  7. Paste the converted text (clipboard swap + Ctrl+V) - this replaces the
     active selection. Terminals: clear the input line, paste with the
     configured terminal combo.
  8. Switch the system layout to the target.
  9. Restore the user's clipboard.

Only one conversion runs at a time; a hotkey pressed while one is in flight is
dropped. Any exception is logged; the daemon never crashes. Text content is
never logged.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Callable

from sgk_wordwrap.core.layout_manager import SgkLayoutManager
from sgk_wordwrap.input.clipboard import SgkClipboard, SgkClipboardBlob
from sgk_wordwrap.layouts.detector import SgkFieldDetector
from sgk_wordwrap.layouts.mapper import SgkLayoutMapper
from sgk_wordwrap.utils.logger import sgk_get_logger

_logger = sgk_get_logger(__name__)

_PASTE_COMBO = "ctrl+v"
_COPY_POLL_S = 0.04
_MODIFIER_RELEASE_MAX_S = 0.6
_COPY_ATTEMPTS = 2
_MARKER_PREFIX = "sgk-wordwrap-"
_SWITCH_POLL_S = 0.04
_SWITCH_WAIT_LIVE_S = 0.4
_SWITCH_WAIT_MRU_S = 0.25
_REPEAT_WINDOW_S = 4.0

_SgkSaved = str | SgkClipboardBlob | None


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
        restore_clipboard: bool = True,
        settle_ms: int = 150,
        copy_settle_ms: int = 300,
        layout_settle_ms: int = 60,
        terminal_paste_combo: str = "ctrl+shift+v",
        terminal_erase: str = "line",
        terminal_settle_ms: int = 300,
        terminal_max_backspaces: int = 200,
        modifiers_held: Callable[[], bool] | None = None,
    ) -> None:
        self._clipboard = clipboard
        self._layout_manager = layout_manager
        self._mapper = mapper
        self._detector = detector
        self._max_length = max_text_length
        self._fallback_to_word = fallback_to_word
        self._restore_clipboard = restore_clipboard
        self._settle = settle_ms / 1000.0
        self._copy_settle = copy_settle_ms / 1000.0
        self._layout_settle = layout_settle_ms / 1000.0
        self._terminal_paste_combo = terminal_paste_combo
        self._terminal_erase = terminal_erase
        self._terminal_settle = terminal_settle_ms / 1000.0
        self._terminal_max_backspaces = terminal_max_backspaces
        self._modifiers_held = modifiers_held
        self._busy = False
        self._sgk_last_target: tuple[str, float] | None = None

    async def sgk_process(self, mode: str = "convert") -> None:
        """Entry point - called when a convert hotkey fires.

        `mode` is the hotkey name: "convert" (selection), "convert_terminal"
        (erase + paste, for real terminals), "convert_last_word" (no selection
        needed - grabs the last word).
        """
        if self._busy:
            _logger.debug("sgk_process_busy", extra={"mode": mode})
            return
        self._busy = True
        t_start = time.monotonic()
        try:
            if mode == "convert_terminal":
                await asyncio.sleep(self._terminal_settle)
                await self._sgk_wait_modifiers_released()
                await self._sgk_do_process_terminal()
            else:
                await asyncio.sleep(self._settle)
                await self._sgk_wait_modifiers_released()
                await self._sgk_do_process(last_word=mode == "convert_last_word")
        except Exception as exc:
            _logger.error("sgk_process_unexpected_error", extra={"error": str(exc)})
        finally:
            self._busy = False
            _logger.debug(
                "sgk_process_done",
                extra={"latency_ms": round((time.monotonic() - t_start) * 1000)},
            )

    async def _sgk_wait_modifiers_released(self) -> None:
        if self._modifiers_held is None:
            return
        t0 = time.monotonic()
        while self._modifiers_held() and time.monotonic() - t0 < _MODIFIER_RELEASE_MAX_S:
            await asyncio.sleep(0.02)
        waited = round((time.monotonic() - t0) * 1000)
        if waited:
            _logger.debug(
                "sgk_waited_for_modifier_release",
                extra={"wait_ms": waited, "still_held": bool(self._modifiers_held())},
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

        saved_clipboard = await self._sgk_save_clipboard()
        restored = False
        try:
            repeat_target = None if last_word else self._sgk_recent_target()
            if repeat_target is not None and await self._sgk_layout_is(repeat_target):
                repeat_target = None
            text = await self._sgk_acquire_text(
                saved_clipboard if isinstance(saved_clipboard, str) else None,
                force_word=last_word,
                allow_word=repeat_target is None,
            )
            if not text and repeat_target is not None:
                self._sgk_last_target = None
                _logger.info("sgk_repeat_press_layout_only", extra={"want": repeat_target})
                await self._sgk_switch_layout(repeat_target)
                restored = True
                await self._sgk_restore(saved_clipboard, force=True)
                return
            if not text:
                _logger.debug("sgk_no_text_acquired")
                restored = True
                await self._sgk_restore(saved_clipboard, force=True)
                return
            self._sgk_last_target = None

            prepared = self._sgk_prepare(text)
            if prepared is None:
                restored = True
                await self._sgk_restore(saved_clipboard, force=True)
                return
            converted, layout_before, layout_after = prepared

            if not await self._clipboard.sgk_paste_text(converted, _PASTE_COMBO):
                restored = True
                await self._sgk_restore(saved_clipboard, force=True)
                return
            layout_now = await self._sgk_switch_layout(layout_after)
            self._sgk_last_target = (layout_after, time.monotonic())
            restored = True
            await self._sgk_restore(saved_clipboard)
            self._sgk_log_convert(
                layout_before, layout_after, len(text), terminal=False, layout_now=layout_now
            )
        except Exception:
            if not restored:
                await self._sgk_restore(saved_clipboard, force=True)
            raise

    def _sgk_recent_target(self) -> str | None:
        last = self._sgk_last_target
        if last is None:
            return None
        target, ts = last
        if time.monotonic() - ts > _REPEAT_WINDOW_S:
            self._sgk_last_target = None
            return None
        return target

    async def _sgk_layout_is(self, target: str) -> bool:
        await asyncio.sleep(self._layout_settle)
        lm = self._layout_manager
        per_window = lm.sgk_per_window()
        live = lm.sgk_get_live_layout() if per_window else None
        if per_window and live is None:
            return False
        return (live if live is not None else lm.sgk_get_mru_layout()) == target

    async def _sgk_save_clipboard(self) -> _SgkSaved:
        saved = await self._clipboard.sgk_get()
        if saved is not None:
            return saved
        return await self._clipboard.sgk_snapshot_non_text()

    async def _sgk_do_process_terminal(self) -> None:
        """Terminal flow: erase the mistyped text and paste the fixed text.

        Real terminals have no editable selection and no 'replace on paste', and
        Ctrl+Insert / Ctrl+Shift+Left mean different things per terminal. So:
        take the text from the mouse selection (PRIMARY), clear the input line,
        then paste the converted text with the configured terminal paste
        shortcut. PRIMARY is cleared afterwards so a stale selection from some
        other window cannot be replayed by the next hotkey press.

        Assumes the mistyped text is the current input line (you typed it,
        noticed, selected it, hit the hotkey).
        """
        if self._sgk_sensitive():
            return

        raw = await self._clipboard.sgk_get_primary()
        if not raw or not raw.strip():
            _logger.info("sgk_terminal_no_selection")
            return

        text = raw.strip()
        if "\n" in text:
            _logger.warning("sgk_terminal_multiline_selection", extra={"len": len(text)})
            return

        prepared = self._sgk_prepare(text)
        if prepared is None:
            return
        converted, layout_before, layout_after = prepared

        saved_clipboard = await self._sgk_save_clipboard()
        restored = False
        try:
            if not await self._sgk_terminal_erase(text):
                restored = True
                await self._sgk_restore(saved_clipboard, force=True)
                return

            if not await self._clipboard.sgk_paste_text(converted, self._terminal_paste_combo):
                restored = True
                await self._sgk_restore(saved_clipboard, force=True)
                return
            await self._clipboard.sgk_clear_primary()
            layout_now = await self._sgk_switch_layout(layout_after)
            restored = True
            await self._sgk_restore(saved_clipboard)
            self._sgk_log_convert(
                layout_before, layout_after, len(text), terminal=True, layout_now=layout_now
            )
        except Exception:
            if not restored:
                await self._sgk_restore(saved_clipboard, force=True)
            raise

    def _sgk_prepare(self, text: str) -> tuple[str, str, str] | None:
        if not SgkClipboard.sgk_is_text_safe(text, self._max_length):
            _logger.debug("sgk_text_unsafe", extra={"len": len(text)})
            return None

        layout_before, layout_after = self._sgk_pick_direction(text)
        if not self._mapper.sgk_has_map(layout_before, layout_after):
            _logger.warning(
                "sgk_no_map", extra={"from": layout_before, "to": layout_after}
            )
            return None

        converted = self._mapper.sgk_convert(text, layout_before, layout_after)
        if converted == text:
            _logger.debug("sgk_no_change_after_convert")
            return None
        return converted, layout_before, layout_after

    def _sgk_log_convert(
        self,
        layout_before: str,
        layout_after: str,
        char_count: int,
        terminal: bool,
        layout_now: str | None = None,
    ) -> None:
        proc, win_class, _ = self._detector.sgk_get_active_window_info()
        _logger.info(
            "sgk_convert",
            extra={
                "app": proc or "unknown",
                "window_class": win_class or "unknown",
                "layout_before": layout_before,
                "layout_after": layout_after,
                "layout_now": layout_now,
                "char_count": char_count,
                "terminal": terminal,
            },
        )

    async def _sgk_terminal_erase(self, text: str) -> bool:
        """Erase `text` from the terminal input line. Returns False to abort.

        - "line"      : Ctrl+A then Ctrl+K - clears the whole input line
                        (robust: no keystroke counting; the old text goes to the
                        readline kill-ring, Ctrl+Y restores it).
        - "word"      : Ctrl+W once per whitespace-separated token.
        - "backspace" : Backspace once per character (needs the mistyped text to
                        be exactly at the cursor; keystrokes can be dropped).
        """
        mode = self._terminal_erase
        if mode == "backspace":
            if len(text) > self._terminal_max_backspaces:
                _logger.warning(
                    "sgk_terminal_too_long",
                    extra={"len": len(text), "max": self._terminal_max_backspaces},
                )
                return False
            await self._clipboard.sgk_backspace(len(text))
        elif mode == "word":
            for _ in range(max(1, len(text.split()))):
                await self._clipboard.sgk_send_key("ctrl+w")
        else:
            await self._clipboard.sgk_send_key("ctrl+a")
            await self._clipboard.sgk_send_key("ctrl+k")
        return True

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
        target = next(
            (o for o in others if self._mapper.sgk_has_map(source, o)),
            others[0] if others else self._layout_manager.sgk_get_next_layout(),
        )
        _logger.debug(
            "sgk_direction",
            extra={"detected": detected, "source": source, "target": target},
        )
        return source, target

    async def _sgk_acquire_text(
        self,
        saved_clipboard: str | None,
        force_word: bool = False,
        allow_word: bool = True,
    ) -> str | None:
        """Get the text to convert.

        PRIMARY persists the last mouse selection forever on Linux, so it cannot
        tell us whether something is selected *now*. Instead a private marker is
        put on the CLIPBOARD, the selection is copied over it with a copy
        shortcut, and the clipboard is read back: still the marker means nothing
        is selected, so (optionally) select the last word ourselves. Comparing
        against a marker rather than the saved clipboard matters when the user
        selects exactly what they copied a moment ago.

        `force_word=True` (the "convert last word" hotkey) skips the "is
        something already selected?" check and always selects the last word.

        The copy shortcut is Ctrl+Insert, not Ctrl+C: in a terminal Ctrl+C is
        SIGINT and would kill the foreground program.
        """
        marker = f"{_MARKER_PREFIX}{uuid.uuid4().hex}"
        confirmed = await self._clipboard.sgk_set(marker, confirm=True)
        baseline = marker if confirmed else saved_clipboard

        if not force_word:
            for _ in range(_COPY_ATTEMPTS):
                text = await self._sgk_copy_selection(baseline)
                if self._sgk_is_fresh(text, baseline):
                    _logger.debug("sgk_acquired_via_selection", extra={"len": len(text)})
                    return text
            if not self._fallback_to_word or not allow_word:
                return None

        await self._clipboard.sgk_send_key("ctrl+shift+Left")
        await asyncio.sleep(0.12)
        text = await self._sgk_copy_selection(baseline)
        if self._sgk_is_fresh(text, baseline):
            _logger.debug("sgk_acquired_via_word_selection", extra={"len": len(text)})
            return text
        await self._clipboard.sgk_send_key("right")
        _logger.info("sgk_word_fallback_failed")
        return None

    @staticmethod
    def _sgk_is_fresh(text: str | None, baseline: str | None) -> bool:
        return bool(
            text and text.strip() and text != baseline and not text.startswith(_MARKER_PREFIX)
        )

    async def _sgk_copy_selection(self, baseline: str | None) -> str | None:
        """Copy the current selection into CLIPBOARD (Ctrl+Insert) and read it.

        Apps publish the new clipboard content with very different latency
        (browsers can take a few hundred ms), so poll until it differs from
        `baseline` or `copy_settle` runs out.
        """
        await self._clipboard.sgk_send_key("ctrl+insert")
        t0 = time.monotonic()
        text = None
        while True:
            await asyncio.sleep(min(_COPY_POLL_S, self._copy_settle))
            text = await self._clipboard.sgk_get()
            waited = time.monotonic() - t0
            if self._sgk_is_fresh(text, baseline) or waited >= self._copy_settle:
                break
        _logger.debug(
            "sgk_copy_read",
            extra={"wait_ms": round(waited * 1000), "fresh": self._sgk_is_fresh(text, baseline)},
        )
        return text

    async def _sgk_switch_layout(self, target: str) -> str | None:
        """Switch the system layout to `target` and return the layout read back.

        GNOME ignores `gsettings set ... current`, so the GNOME 'switch input
        source' shortcut (default Super+Space) is pressed through uinput. With
        per-window input sources `mru-sources` is stale for the focused window,
        so the live layout is read from `ibus engine`; without it the shortcut
        is pressed and the result is read from `mru-sources`, which GNOME
        rewrites on every interactive switch.
        """
        lm = self._layout_manager
        if not lm.sgk_uses_shortcut_switch():
            return await self._sgk_switch_layout_legacy(target)

        await asyncio.sleep(self._layout_settle)
        per_window = lm.sgk_per_window()
        live = lm.sgk_get_live_layout() if per_window else None
        readback = "ibus" if live is not None else "mru"
        reliable = live is not None or not per_window
        before = live if live is not None else lm.sgk_get_mru_layout()
        active = lm.sgk_get_active_layouts()
        now = before
        presses = 0
        if not (reliable and before == target):
            shortcut = lm.sgk_get_switch_shortcut()
            wait_s = _SWITCH_WAIT_LIVE_S if reliable else _SWITCH_WAIT_MRU_S
            for _ in range(max(1, len(active))):
                taps = self._sgk_switch_taps(target, now, active, lm.sgk_get_mru_layouts())
                await self._clipboard.sgk_send_key_repeat(shortcut, taps)
                presses += 1
                previous = now
                now = await self._sgk_wait_layout_change(previous, readback, wait_s)
                if now == target:
                    break
                if reliable and now == previous:
                    break
        extra = {
            "want": target,
            "before": before,
            "now": now,
            "presses": presses,
            "per_window": per_window,
            "readback": readback,
        }
        if now == target:
            _logger.debug("sgk_layout_after_switch", extra=extra)
        else:
            _logger.warning("sgk_layout_switch_failed", extra=extra)
        return now

    @staticmethod
    def _sgk_switch_taps(
        target: str, current: str, active: list[str], mru: list[str]
    ) -> int:
        if len(active) <= 2:
            return 1
        order = [current] + [m for m in mru if m != current]
        order += [a for a in active if a not in order]
        if target not in order:
            return 1
        return min(max(1, order.index(target)), len(active) - 1)

    async def _sgk_wait_layout_change(self, previous: str, readback: str, wait_s: float) -> str:
        lm = self._layout_manager
        t0 = time.monotonic()
        value = previous
        while True:
            await asyncio.sleep(_SWITCH_POLL_S)
            read = lm.sgk_get_live_layout() if readback == "ibus" else None
            value = read if read is not None else lm.sgk_get_mru_layout()
            if value != previous or time.monotonic() - t0 >= wait_s:
                return value

    async def _sgk_switch_layout_legacy(self, target: str) -> str | None:
        self._layout_manager.sgk_switch_to(target)
        await asyncio.sleep(self._layout_settle)
        if self._layout_manager.sgk_layout_matches(target):
            return target

        shortcut = self._layout_manager.sgk_get_switch_shortcut()
        tries = max(1, len(self._layout_manager.sgk_get_active_layouts()))
        for _ in range(tries):
            await self._clipboard.sgk_send_key(shortcut)
            await asyncio.sleep(0.08)
            if self._layout_manager.sgk_layout_matches(target):
                break
        now = self._layout_manager.sgk_get_current_layout()
        _logger.debug(
            "sgk_layout_after_switch",
            extra={"want": target, "now": now, "used_shortcut": shortcut},
        )
        return now

    async def _sgk_restore(self, saved: _SgkSaved, force: bool = False) -> None:
        if not force and not self._restore_clipboard:
            return
        await asyncio.sleep(0.05)
        if saved is None:
            await self._clipboard.sgk_clear()
        elif isinstance(saved, SgkClipboardBlob):
            if not await self._clipboard.sgk_set_blob(saved):
                await self._clipboard.sgk_clear()
        else:
            await self._clipboard.sgk_set(saved)
