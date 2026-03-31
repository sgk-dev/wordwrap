"""Clipboard and key simulation abstraction layer.

Supports X11 (xclip + xdotool) and Wayland (wl-clipboard + ydotool/wtype).
All operations are async to avoid blocking the event loop.
"""

from __future__ import annotations

import asyncio
import shutil
from typing import Any

from sgk_wordwrap.utils.display_server import sgk_detect_display_server
from sgk_wordwrap.utils.logger import sgk_get_logger

_logger = sgk_get_logger(__name__)

_CLIPBOARD_TIMEOUT = 0.5   # seconds per subprocess call
_RETRY_DELAY = 0.05        # seconds between retries
_RETRIES = 2


class SgkClipboard:
    """Clipboard read/write and keyboard simulation for X11 and Wayland."""

    def __init__(self, action_delay_ms: int = 50) -> None:
        self._display = sgk_detect_display_server()
        self._delay = action_delay_ms / 1000.0
        self._saved_clipboard: str | None = None

    # ------------------------------------------------------------------
    # Clipboard operations
    # ------------------------------------------------------------------

    async def sgk_get(self) -> str | None:
        """Read current clipboard text. Returns None on failure."""
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

    async def sgk_set(self, text: str) -> bool:
        """Write text to clipboard. Returns True on success."""
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
        """Save current clipboard for later restoration."""
        self._saved_clipboard = await self.sgk_get()

    async def sgk_restore(self) -> None:
        """Restore previously saved clipboard."""
        if self._saved_clipboard is not None:
            await self.sgk_set(self._saved_clipboard)
            self._saved_clipboard = None

    # ------------------------------------------------------------------
    # Key simulation
    # ------------------------------------------------------------------

    async def sgk_send_key(self, combo: str) -> None:
        """Simulate a key combination (e.g., 'ctrl+c', 'ctrl+shift+Left').

        Uses xdotool on X11 and ydotool/wtype on Wayland.
        """
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
        # xdotool key --clearmodifiers ctrl+c
        xdotool_combo = combo.replace("+", "+")  # already in xdotool format
        proc = await asyncio.create_subprocess_exec(
            "xdotool", "key", "--clearmodifiers", xdotool_combo,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.wait(), timeout=_CLIPBOARD_TIMEOUT)

    async def _sgk_send_key_wayland(self, combo: str) -> None:
        # Try ydotool first, fall back to wtype
        if shutil.which("ydotool"):
            ydotool_key = self._sgk_combo_to_ydotool(combo)
            proc = await asyncio.create_subprocess_exec(
                "ydotool", "key", ydotool_key,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.wait(), timeout=_CLIPBOARD_TIMEOUT)
        else:
            _logger.warning("sgk_ydotool_not_found", extra={"hint": "Install ydotool"})

    def _sgk_combo_to_ydotool(self, combo: str) -> str:
        """Convert 'ctrl+c' to ydotool key format."""
        # ydotool uses KEY_LEFTCTRL+KEY_C format
        _map = {
            "ctrl": "KEY_LEFTCTRL",
            "shift": "KEY_LEFTSHIFT",
            "alt": "KEY_LEFTALT",
            "super": "KEY_LEFTMETA",
        }
        parts = combo.split("+")
        result = []
        for part in parts:
            lower = part.lower()
            if lower in _map:
                result.append(_map[lower])
            else:
                result.append(f"KEY_{part.upper()}")
        return "+".join(result)

    # ------------------------------------------------------------------
    # Convenience: copy–convert–paste cycle
    # ------------------------------------------------------------------

    async def sgk_copy(self) -> str | None:
        """Simulate Ctrl+C and return the new clipboard content."""
        before = await self.sgk_get()
        await self.sgk_send_key("ctrl+c")
        await asyncio.sleep(self._delay * 2)
        after = await self.sgk_get()
        if after and after != before:
            return after
        return None

    async def sgk_paste(self, text: str) -> None:
        """Set clipboard to text and simulate Ctrl+V."""
        await self.sgk_set(text)
        await self.sgk_send_key("ctrl+v")

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
        """Return True if content is non-empty text within safe bounds."""
        if not isinstance(content, str):
            return False
        stripped = content.strip()
        if not stripped:
            return False
        if len(stripped) > max_length:
            return False
        return True
