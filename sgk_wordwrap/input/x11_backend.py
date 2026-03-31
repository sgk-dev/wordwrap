"""X11 global hotkey listener using the XRecord extension.

Requires: python-xlib >= 0.33
Does NOT require root or udev rules.

Architecture:
  - Two Display connections: one for the record context, one for control
  - XRecord captures all KeyPress/KeyRelease events system-wide
  - Runs in a daemon thread; fires callback via asyncio loop
"""

from __future__ import annotations

import threading
from typing import Callable

from sgk_wordwrap.input.base import SgkInputBackend
from sgk_wordwrap.utils.logger import sgk_get_logger

_logger = sgk_get_logger(__name__)


def _sgk_parse_hotkey(hotkey_str: str) -> tuple[frozenset[str], str]:
    """Parse 'ctrl+shift+z' → (frozenset({'ctrl', 'shift'}), 'z')."""
    parts = [p.strip().lower() for p in hotkey_str.split("+")]
    modifiers = frozenset(p for p in parts[:-1])
    key = parts[-1]
    return modifiers, key


_SGK_MODIFIER_KEYSYMS: dict[str, list[str]] = {
    "ctrl":  ["Control_L", "Control_R"],
    "shift": ["Shift_L", "Shift_R"],
    "alt":   ["Alt_L", "Alt_R"],
    "super": ["Super_L", "Super_R"],
    "meta":  ["Meta_L", "Meta_R"],
}


class SgkX11HotkeyListener(SgkInputBackend):
    """Global hotkey listener for X11 using XRecord."""

    def __init__(self, hotkey_str: str = "ctrl+shift+z") -> None:
        self._hotkey_str = hotkey_str
        self._modifiers, self._trigger_key = _sgk_parse_hotkey(hotkey_str)
        self._callback: Callable[[], None] | None = None
        self._thread: threading.Thread | None = None
        self._ctx = None
        self._record_dpy = None
        self._local_dpy = None
        self._pressed_keysyms: set[str] = set()
        self._running = False

    def sgk_is_available(self) -> bool:
        try:
            from Xlib import display as xdisplay
            from Xlib.ext import record  # noqa: F401
            dpy = xdisplay.Display()
            dpy.close()
            return True
        except Exception:
            return False

    def sgk_start(self, on_hotkey: Callable[[], None]) -> None:
        self._callback = on_hotkey
        self._running = True
        self._thread = threading.Thread(
            target=self._sgk_run_record_loop,
            name="sgk-x11-record",
            daemon=True,
        )
        self._thread.start()
        _logger.info("sgk_x11_listener_started", extra={"hotkey": self._hotkey_str})

    def sgk_stop(self) -> None:
        self._running = False
        try:
            if self._ctx is not None and self._local_dpy is not None:
                self._local_dpy.record_disable_context(self._ctx)
                self._local_dpy.flush()
        except Exception as exc:
            _logger.debug("sgk_x11_stop_error", extra={"error": str(exc)})

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

        if self._record_dpy:
            try:
                self._record_dpy.close()
            except Exception:
                pass
        if self._local_dpy:
            try:
                self._local_dpy.close()
            except Exception:
                pass

        _logger.info("sgk_x11_listener_stopped")

    def _sgk_run_record_loop(self) -> None:
        try:
            from Xlib import X
            from Xlib import display as xdisplay
            from Xlib.ext import record
            from Xlib.protocol import rq

            self._record_dpy = xdisplay.Display()
            self._local_dpy = xdisplay.Display()

            if not self._record_dpy.has_extension("RECORD"):
                _logger.error("sgk_x11_record_ext_missing")
                return

            # Build keysym lookup tables
            trigger_keycode = self._sgk_keysym_to_keycode(
                self._local_dpy, self._trigger_key
            )
            modifier_keycodes: set[int] = set()
            for mod_name in self._modifiers:
                for ksym_name in _SGK_MODIFIER_KEYSYMS.get(mod_name, []):
                    kc = self._sgk_keysym_to_keycode(self._local_dpy, ksym_name)
                    if kc:
                        modifier_keycodes.add(kc)

            pressed: set[int] = set()

            def _handler(reply: object) -> None:
                if not self._running:
                    return
                if reply.category != record.FromServer:  # type: ignore[attr-defined]
                    return
                if reply.client_swapped:  # type: ignore[attr-defined]
                    return
                data = reply.data  # type: ignore[attr-defined]
                if not data or data[0] < 2:
                    return

                while data:
                    event, data = rq.EventField(None).parse(data, self._record_dpy)
                    keycode = event.detail
                    if event.type == X.KeyPress:
                        pressed.add(keycode)
                        # Check if hotkey is satisfied
                        if (
                            trigger_keycode
                            and keycode == trigger_keycode
                            and modifier_keycodes.issubset(pressed)
                        ):
                            _logger.debug("sgk_hotkey_triggered")
                            if self._callback:
                                self._callback()
                    elif event.type == X.KeyRelease:
                        pressed.discard(keycode)

            self._ctx = self._record_dpy.record_create_context(
                0,
                [record.AllClients],
                [{
                    "core_requests": (0, 0),
                    "core_replies": (0, 0),
                    "ext_requests": (0, 0, 0, 0),
                    "ext_replies": (0, 0, 0, 0),
                    "delivered_events": (0, 0),
                    "device_events": (X.KeyPress, X.KeyRelease),
                    "errors": (0, 0),
                    "client_started": False,
                    "client_died": False,
                }],
            )
            self._record_dpy.record_enable_context(self._ctx, _handler)

        except Exception as exc:
            _logger.error("sgk_x11_record_loop_error", extra={"error": str(exc)})

    def _sgk_keysym_to_keycode(self, dpy: object, name: str) -> int | None:
        try:
            from Xlib import XK
            keysym = XK.string_to_keysym(name)
            if keysym == 0:
                # Try direct character (e.g., 'z' → 'z')
                keysym = ord(name) if len(name) == 1 else 0
            if keysym == 0:
                return None
            keycode = dpy.keysym_to_keycode(keysym)  # type: ignore[attr-defined]
            return keycode if keycode != 0 else None
        except Exception:
            return None
