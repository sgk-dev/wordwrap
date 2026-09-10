"""Hotkey manager.

Owns the evdev (Wayland) / X11 hotkey backend and bridges its background-thread
callbacks onto the asyncio event loop. Handles several named hotkeys:

  - ``convert``           - fix the selected text
  - ``convert_terminal``  - same, but paste with Ctrl+Shift+V (terminals)
  - ``toggle``            - enable/disable conversion (works while paused)
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

_MIN_INTERVAL = 0.3  # seconds - debounce repeated triggers, per hotkey

_DEFAULT_HOTKEYS: dict[str, str] = {
    "convert": "ctrl+f1",
    "convert_terminal": "ctrl+shift+f1",
    "toggle": "ctrl+pause",
}


class SgkHotkeyManager:
    """Listens for the configured hotkeys and routes them onto the loop."""

    def __init__(self, hotkeys: dict[str, str] | None = None) -> None:
        self._hotkeys = {**_DEFAULT_HOTKEYS, **(hotkeys or {})}
        self._backend: SgkInputBackend | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._convert_handler: Callable[[bool], None] | None = None
        self._toggle_handler: Callable[[], None] | None = None
        self._last_trigger: dict[str, float] = {}
        self._paused = False
        self._lock = threading.Lock()

    # -- wiring ------------------------------------------------------

    def sgk_set_handler(self, handler: Callable[[bool], None]) -> None:
        """`handler(terminal: bool)` runs a conversion. Called on the loop thread."""
        self._convert_handler = handler

    def sgk_set_toggle_handler(self, handler: Callable[[], None]) -> None:
        """`handler()` flips enabled/disabled. Called on the loop thread."""
        self._toggle_handler = handler

    def sgk_start(self, loop: asyncio.AbstractEventLoop) -> None:
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
            extra={"hotkeys": self._hotkeys, "display": sgk_detect_display_server()},
        )

    def sgk_stop(self) -> None:
        if self._backend:
            self._backend.sgk_stop()
        _logger.info("sgk_hotkey_manager_stopped")

    # -- pause state ----------------------------------------------

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

    # -- dispatch -------------------------------------------------

    def _sgk_debounced(self, name: str) -> bool:
        now = time.monotonic()
        if now - self._last_trigger.get(name, 0.0) < _MIN_INTERVAL:
            return False
        self._last_trigger[name] = now
        return True

    def _sgk_on_hotkey_raw(self, name: str) -> None:
        """Called from the evdev background thread."""
        with self._lock:
            if not self._sgk_debounced(name):
                return
            paused = self._paused

        if name == "toggle":
            if self._loop and self._toggle_handler:
                self._loop.call_soon_threadsafe(self._toggle_handler)
            return

        if paused:
            return

        terminal = name == "convert_terminal"
        if self._loop and self._convert_handler:
            self._loop.call_soon_threadsafe(self._convert_handler, terminal)

    # -- backend selection --------------------------------------

    def _sgk_pick_backend(self) -> SgkInputBackend | None:
        if sgk_detect_display_server() == "x11":
            from sgk_wordwrap.input.x11_backend import SgkX11HotkeyListener

            backend = SgkX11HotkeyListener(self._hotkeys["convert"])
            # X11 backend is single-hotkey; adapt its 0-arg callback.
            orig_start = backend.sgk_start

            def _start(cb):  # noqa: ANN001
                orig_start(lambda: cb("convert"))

            backend.sgk_start = _start  # type: ignore[method-assign]
            return backend

        from sgk_wordwrap.input.evdev_backend import SgkEvdevHotkeyListener

        return SgkEvdevHotkeyListener(self._hotkeys)

    def _sgk_get_unavailable_hint(self) -> str:
        if sgk_detect_display_server() == "wayland":
            return (
                "Wayland: add yourself to the 'input' group: "
                "sudo usermod -aG input $USER  (then log out and back in)"
            )
        return "X11: ensure python-xlib is installed and RECORD extension is available"
