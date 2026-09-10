"""Clipboard and key simulation abstraction layer.

X11:     xclip + xdotool
Wayland: wl-clipboard (wl-paste/wl-copy) + wtype for text input

Key insight for Wayland:
  - Selected text is automatically placed in PRIMARY selection - no Ctrl+C needed.
  - Read selected text with: wl-paste --primary
  - Type replacement text with: wtype "text"  (replaces active selection)
"""

from __future__ import annotations

import asyncio
import shutil
from typing import Any

from sgk_wordwrap.input.uinput_backend import SgkUinputInjector
from sgk_wordwrap.utils.display_server import sgk_detect_display_server
from sgk_wordwrap.utils.logger import sgk_get_logger

_logger = sgk_get_logger(__name__)

_CLIPBOARD_TIMEOUT = 0.5
_RETRY_DELAY = 0.05
_RETRIES = 2


class SgkClipboard:
    """Clipboard read/write and text input for X11 and Wayland."""

    def __init__(
        self,
        action_delay_ms: int = 50,
        clipboard_settle_ms: int = 80,
        paste_settle_ms: int = 80,
        uinput: SgkUinputInjector | None = None,
    ) -> None:
        self._display = sgk_detect_display_server()
        self._delay = action_delay_ms / 1000.0
        self._clipboard_settle = clipboard_settle_ms / 1000.0
        self._paste_settle = paste_settle_ms / 1000.0
        self._saved_clipboard: str | None = None

        # Wayland-specific injector (uinput virtual keyboard)
        self._uinput: SgkUinputInjector | None = uinput
        if self._uinput is None and self._display == "wayland":
            self._uinput = SgkUinputInjector()

    # ------------------------------------------------------------------
    # Clipboard (CLIPBOARD selection)
    # ------------------------------------------------------------------

    async def sgk_get(self) -> str | None:
        """Read CLIPBOARD selection. Returns None on failure."""
        for attempt in range(_RETRIES):
            try:
                if self._display == "wayland":
                    return await self._sgk_run_get(["wl-paste", "--no-newline"])
                else:
                    return await self._sgk_run_get(
                        ["xclip", "-selection", "clipboard", "-o"]
                    )
            except Exception as exc:
                if attempt < _RETRIES - 1:
                    await asyncio.sleep(_RETRY_DELAY)
                else:
                    _logger.warning("sgk_clipboard_get_failed", extra={"error": str(exc)})
        return None

    async def sgk_get_primary(self) -> str | None:
        """Read PRIMARY selection (Wayland: currently selected text, no Ctrl+C needed)."""
        try:
            if self._display == "wayland":
                return await self._sgk_run_get(["wl-paste", "--primary", "--no-newline"])
            else:
                return await self._sgk_run_get(
                    ["xclip", "-selection", "primary", "-o"]
                )
        except Exception as exc:
            _logger.debug("sgk_primary_get_failed", extra={"error": str(exc)})
        return None

    async def sgk_set(self, text: str) -> bool:
        """Write text to CLIPBOARD. Returns True on success."""
        for attempt in range(_RETRIES):
            try:
                if self._display == "wayland":
                    await self._sgk_run_set(["wl-copy"], text)
                else:
                    await self._sgk_run_set(
                        ["xclip", "-selection", "clipboard", "-i"], text
                    )
                return True
            except Exception as exc:
                if attempt < _RETRIES - 1:
                    await asyncio.sleep(_RETRY_DELAY)
                else:
                    _logger.warning("sgk_clipboard_set_failed", extra={"error": str(exc)})
        return False

    async def sgk_save(self) -> None:
        self._saved_clipboard = await self.sgk_get()

    async def sgk_restore(self) -> None:
        if self._saved_clipboard is not None:
            await self.sgk_set(self._saved_clipboard)
            self._saved_clipboard = None

    # ------------------------------------------------------------------
    # Text input (replaces selected text in focused app)
    # ------------------------------------------------------------------

    async def sgk_type_text(self, text: str, terminal: bool = False) -> bool:
        """Deliver `text` into the focused app, replacing any active selection.

        Wayland: clipboard swap + synthetic paste (Ctrl+V, or Ctrl+Shift+V when
        `terminal` is True). `wtype` is unsupported by Mutter and keycode typing
        is layout-dependent, so this is the only reliable path.
        X11: xdotool type.
        The caller is responsible for saving/restoring the user's clipboard
        around this call.
        Returns True if the paste was issued.
        """
        await asyncio.sleep(self._delay)
        try:
            if self._display == "wayland":
                return await self._sgk_type_wayland(text, terminal)
            return await self._sgk_type_x11(text)
        except Exception as exc:
            _logger.warning("sgk_type_text_failed", extra={"error": str(exc)})
            return False

    async def _sgk_type_wayland(self, text: str, terminal: bool) -> bool:
        """Put `text` on the CLIPBOARD and issue a synthetic paste via uinput."""
        if not (self._uinput and self._uinput.sgk_is_available()):
            _logger.error(
                "sgk_uinput_unavailable",
                extra={"hint": "uinput virtual keyboard not usable - cannot paste"},
            )
            return False

        await self._sgk_run_set(["wl-copy"], text)
        await asyncio.sleep(self._clipboard_settle)
        self._uinput.sgk_paste(shift=terminal)
        await asyncio.sleep(self._paste_settle)
        return True

    async def _sgk_type_x11(self, text: str) -> bool:
        proc = await asyncio.create_subprocess_exec(
            "xdotool", "type", "--clearmodifiers", "--", text,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.wait(), timeout=_CLIPBOARD_TIMEOUT + len(text) * 0.002)
        return proc.returncode == 0

    async def sgk_backspace(self, count: int) -> None:
        """Press Backspace `count` times (erase text, e.g. in a terminal)."""
        if count <= 0:
            return
        await asyncio.sleep(self._delay)
        try:
            if self._display == "wayland" and self._uinput and self._uinput.sgk_is_available():
                self._uinput.sgk_backspace(count)
            else:
                proc = await asyncio.create_subprocess_exec(
                    "xdotool", "key", "--clearmodifiers",
                    *(["BackSpace"] * count),
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await asyncio.wait_for(proc.wait(), timeout=_CLIPBOARD_TIMEOUT + count * 0.01)
        except Exception as exc:
            _logger.warning("sgk_backspace_failed", extra={"error": str(exc)})

    async def sgk_paste_text(self, text: str, combo: str) -> bool:
        """Put `text` on the CLIPBOARD and paste with an explicit key combo.

        Used for terminals, where the paste shortcut varies (Ctrl+Shift+V,
        Shift+Insert). Caller saves/restores the user's clipboard.
        """
        if not (self._uinput and self._uinput.sgk_is_available()):
            _logger.error("sgk_uinput_unavailable", extra={"hint": "cannot paste"})
            return False
        await self._sgk_run_set(["wl-copy"], text)
        await asyncio.sleep(self._clipboard_settle)
        self._uinput.sgk_send_combo(combo)
        await asyncio.sleep(self._paste_settle)
        return True

    # ------------------------------------------------------------------
    # Key simulation (for word selection fallback only)
    # ------------------------------------------------------------------

    async def sgk_send_key(self, combo: str) -> None:
        """Simulate a key combo. Used for word-selection fallback (Ctrl+Shift+Left)."""
        await asyncio.sleep(self._delay)
        try:
            if self._display == "wayland":
                await self._sgk_send_key_wayland(combo)
            else:
                await self._sgk_send_key_x11(combo)
        except Exception as exc:
            _logger.warning("sgk_send_key_failed", extra={"combo": combo, "error": str(exc)})
        await asyncio.sleep(self._delay)

    async def _sgk_send_key_x11(self, combo: str) -> None:
        proc = await asyncio.create_subprocess_exec(
            "xdotool", "key", "--clearmodifiers", combo,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.wait(), timeout=_CLIPBOARD_TIMEOUT)

    async def _sgk_send_key_wayland(self, combo: str) -> None:
        # 1. Prefer native uinput injector (no external dependencies)
        if self._uinput and self._uinput.sgk_is_available():
            self._uinput.sgk_send_combo(combo)
            return

        # 2. Fallback to wtype
        if shutil.which("wtype"):
            wtype_args = self._sgk_combo_to_wtype(combo)
            if wtype_args:
                proc = await asyncio.create_subprocess_exec(
                    "wtype", *wtype_args,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await asyncio.wait_for(proc.wait(), timeout=_CLIPBOARD_TIMEOUT)
                if proc.returncode == 0:
                    return

        # Fallback to ydotool
        if shutil.which("ydotool"):
            ydotool_key = self._sgk_combo_to_ydotool(combo)
            proc = await asyncio.create_subprocess_exec(
                "ydotool", "key", ydotool_key,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.wait(), timeout=_CLIPBOARD_TIMEOUT)

    def _sgk_combo_to_wtype(self, combo: str) -> list[str] | None:
        """Convert 'ctrl+shift+Left' → ['-M', 'ctrl', '-M', 'shift', '-P', 'left']."""
        _map = {
            "ctrl": "ctrl", "shift": "shift",
            "alt": "alt", "super": "logo", "logo": "logo",
        }
        parts = combo.split("+")
        args = []
        for part in parts[:-1]:
            mod = _map.get(part.lower())
            if not mod:
                return None
            args.extend(["-M", mod])

        last = parts[-1].lower()
        # wtype uses lowercase for key names or specific names
        args.extend(["-P", last])

        # Release modifiers
        for part in reversed(parts[:-1]):
            mod = _map.get(part.lower())
            if mod:
                args.extend(["-m", mod])

        return args

    def _sgk_combo_to_ydotool(self, combo: str) -> str:
        _map = {
            "ctrl": "KEY_LEFTCTRL", "shift": "KEY_LEFTSHIFT",
            "alt": "KEY_LEFTALT", "super": "KEY_LEFTMETA",
        }
        parts = combo.split("+")
        result = []
        for part in parts:
            lower = part.lower()
            if lower in _map:
                result.append(_map[lower])
            else:
                # Handle arrow keys: "Left" → "KEY_LEFT", "BackSpace" → "KEY_BACKSPACE"
                result.append(f"KEY_{part.upper()}")
        return "+".join(result)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _sgk_run_get(self, cmd: list[str]) -> str:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=_CLIPBOARD_TIMEOUT)
        return stdout.decode("utf-8", errors="replace")

    async def _sgk_run_set(self, cmd: list[str], text: str) -> None:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(
            proc.communicate(text.encode("utf-8")),
            timeout=_CLIPBOARD_TIMEOUT,
        )

    @staticmethod
    def sgk_is_text_safe(content: Any, max_length: int = 10000) -> bool:
        if not isinstance(content, str):
            return False
        stripped = content.strip()
        if not stripped:
            return False
        if len(stripped) > max_length:
            return False
        return True
