"""Backend-agnostic hotkey manager.

Selects X11 or evdev backend based on the display server,
bridges background thread callbacks into the asyncio event loop.
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Callable

from sgk_wordwrap.input.base import SgkInputBackend
from sgk_wordwrap.utils.display_server import sgk_detect_display_server
from sgk_wordwrap.utils.logger import sgk_get_logger

_logger = sgk_get_logger(__name__)

_MIN_INTERVAL = 0.3  # seconds — debounce repeated triggers


class SgkHotkeyManager:
    """Manages hotkey listening and routes triggers into an asyncio coroutine."""

    def __init__(self, hotkey_str: str = "ctrl+shift+z") -> None:
        self._hotkey_str = hotkey_str
        self._backend: SgkInputBackend | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._handler: Callable[[], None] | None = None
        self._last_trigger = 0.0
        self._paused = False
        self._lock = threading.Lock()

    def sgk_set_handler(self, coro_factory: Callable[[], None]) -> None:
        """Set the callback to invoke when the hotkey fires.

        coro_factory is a plain synchronous function that schedules a coroutine
        on the event loop.
        """
        self._handler = coro_factory

    def sgk_start(self, loop: asyncio.AbstractEventLoop) -> None:
        """Start listening on the appropriate backend."""
        self._loop = loop
        self._backend = self._sgk_pick_backend()

        if self._backend is None:
            _logger.error("sgk_hotkey_no_backend")
            return

        if not self._backend.sgk_is_available():
            _logger.error(
                "sgk_hotkey_backend_unavailable",
                extra={"hint": self._sgk_get_unavailable_hint()},
            )
            return

        self._backend.sgk_start(self._sgk_on_hotkey_raw)
        _logger.info(
            "sgk_hotkey_manager_started",
            extra={"hotkey": self._hotkey_str, "display": sgk_detect_display_server()},
        )

    def sgk_stop(self) -> None:
        if self._backend:
            self._backend.sgk_stop()
        _logger.info("sgk_hotkey_manager_stopped")

    def sgk_pause(self) -> None:
        with self._lock:
            self._paused = True
        _logger.info("sgk_hotkey_paused")

    def sgk_resume(self) -> None:
        with self._lock:
            self._paused = False
        _logger.info("sgk_hotkey_resumed")

    def sgk_is_paused(self) -> bool:
        return self._paused

    def sgk_get_last_word(self) -> str | None:
        """Get the typed word from the backend buffer (Wayland/evdev only)."""
        if hasattr(self._backend, "sgk_get_last_word"):
            return self._backend.sgk_get_last_word()  # type: ignore
        return None

    def sgk_clear_buffer(self) -> None:
        """Clear the backend's key buffer."""
        if hasattr(self._backend, "sgk_clear_buffer"):
            self._backend.sgk_clear_buffer()  # type: ignore

    def _sgk_on_hotkey_raw(self) -> None:
        """Called from background thread — debounce and forward to event loop."""
        with self._lock:
            if self._paused:
                return
            now = time.monotonic()
            if now - self._last_trigger < _MIN_INTERVAL:
                return
            self._last_trigger = now

        if self._loop and self._handler:
            self._loop.call_soon_threadsafe(self._handler)

    def _sgk_pick_backend(self) -> SgkInputBackend | None:
        display = sgk_detect_display_server()
        if display == "x11":
            from sgk_wordwrap.input.x11_backend import SgkX11HotkeyListener
            return SgkX11HotkeyListener(self._hotkey_str)
        else:
            from sgk_wordwrap.input.evdev_backend import SgkEvdevHotkeyListener
            return SgkEvdevHotkeyListener(self._hotkey_str)

    def _sgk_get_unavailable_hint(self) -> str:
        if sgk_detect_display_server() == "wayland":
            return (
                "Wayland: add yourself to the 'input' group: "
                "sudo usermod -aG input $USER  (then log out and back in)"
            )
        return "X11: ensure python-xlib is installed and RECORD extension is available"
