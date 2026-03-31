"""Wayland/evdev global hotkey listener.

Reads keyboard events directly from /dev/input/event* devices.
Requires user in the 'input' group (or root).

udev rules shipped in packaging/99-sgk-uinput.rules.

Architecture:
  - Enumerates all keyboard input devices via evdev
  - Reads KeyPress/KeyRelease events in a single select() loop
  - Fires callback when the configured hotkey combination is pressed
"""

from __future__ import annotations

import os
import select
import threading
from typing import Callable

from sgk_wordwrap.input.base import SgkInputBackend
from sgk_wordwrap.utils.logger import sgk_get_logger

_logger = sgk_get_logger(__name__)

# evdev key name → KEY_* code mapping (subset for modifier detection)
_SGK_MODIFIER_KEY_NAMES: dict[str, list[str]] = {
    "ctrl":  ["KEY_LEFTCTRL", "KEY_RIGHTCTRL"],
    "shift": ["KEY_LEFTSHIFT", "KEY_RIGHTSHIFT"],
    "alt":   ["KEY_LEFTALT", "KEY_RIGHTALT"],
    "super": ["KEY_LEFTMETA", "KEY_RIGHTMETA"],
}


def _sgk_parse_hotkey(hotkey_str: str) -> tuple[frozenset[str], str]:
    """Parse 'ctrl+shift+z' → (frozenset({'ctrl', 'shift'}), 'z')."""
    parts = [p.strip().lower() for p in hotkey_str.split("+")]
    modifiers = frozenset(p for p in parts[:-1])
    key = parts[-1]
    return modifiers, key


class SgkEvdevHotkeyListener(SgkInputBackend):
    """Global hotkey listener using Linux evdev (Wayland-compatible)."""

    def __init__(self, hotkey_str: str = "ctrl+shift+z") -> None:
        self._hotkey_str = hotkey_str
        self._modifiers, self._trigger_key = _sgk_parse_hotkey(hotkey_str)
        self._callback: Callable[[], None] | None = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._stop_pipe: tuple[int, int] | None = None

    def sgk_is_available(self) -> bool:
        try:
            import evdev  # noqa: F401
            devices = self._sgk_find_keyboards()
            return len(devices) > 0
        except ImportError:
            return False
        except PermissionError:
            _logger.warning(
                "sgk_evdev_no_permission",
                extra={"hint": "Add user to 'input' group: sudo usermod -aG input $USER"},
            )
            return False

    def sgk_start(self, on_hotkey: Callable[[], None]) -> None:
        self._callback = on_hotkey
        self._running = True
        self._stop_pipe = os.pipe()
        self._thread = threading.Thread(
            target=self._sgk_run_evdev_loop,
            name="sgk-evdev",
            daemon=True,
        )
        self._thread.start()
        _logger.info("sgk_evdev_listener_started", extra={"hotkey": self._hotkey_str})

    def sgk_stop(self) -> None:
        self._running = False
        if self._stop_pipe:
            try:
                os.write(self._stop_pipe[1], b"\x00")
            except OSError:
                pass

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

        if self._stop_pipe:
            try:
                os.close(self._stop_pipe[0])
                os.close(self._stop_pipe[1])
            except OSError:
                pass

        _logger.info("sgk_evdev_listener_stopped")

    def _sgk_find_keyboards(self) -> list:
        import evdev
        keyboards = []
        try:
            for path in evdev.list_devices():
                try:
                    dev = evdev.InputDevice(path)
                    caps = dev.capabilities()
                    # Device has EV_KEY events and KEY_A (basic keyboard check)
                    if evdev.ecodes.EV_KEY in caps:
                        if evdev.ecodes.KEY_A in caps[evdev.ecodes.EV_KEY]:
                            keyboards.append(dev)
                        else:
                            dev.close()
                    else:
                        dev.close()
                except (PermissionError, OSError):
                    continue
        except Exception as exc:
            _logger.warning("sgk_evdev_enum_error", extra={"error": str(exc)})
        return keyboards

    def _sgk_run_evdev_loop(self) -> None:
        try:
            import evdev

            keyboards = self._sgk_find_keyboards()
            if not keyboards:
                _logger.error("sgk_evdev_no_keyboards")
                return

            _logger.debug("sgk_evdev_keyboards", extra={"count": len(keyboards)})

            # Build key code sets
            trigger_codes: set[int] = set()
            trigger_name = f"KEY_{self._trigger_key.upper()}"
            code = getattr(evdev.ecodes, trigger_name, None)
            if code is not None:
                trigger_codes.add(code)

            modifier_codes: set[int] = set()
            for mod_name in self._modifiers:
                for key_name in _SGK_MODIFIER_KEY_NAMES.get(mod_name, []):
                    code = getattr(evdev.ecodes, key_name, None)
                    if code is not None:
                        modifier_codes.add(code)

            pressed: set[int] = set()
            stop_r = self._stop_pipe[0] if self._stop_pipe else None

            fds = {dev.fd: dev for dev in keyboards}
            if stop_r is not None:
                fds[stop_r] = None  # type: ignore[assignment]

            while self._running:
                try:
                    readable, _, _ = select.select(list(fds.keys()), [], [], 1.0)
                except (ValueError, OSError):
                    break

                for fd in readable:
                    if fd == stop_r:
                        return

                    dev = fds.get(fd)
                    if dev is None:
                        continue

                    try:
                        for event in dev.read():
                            if event.type != evdev.ecodes.EV_KEY:
                                continue
                            key_event = evdev.categorize(event)
                            code = key_event.scancode

                            if key_event.keystate == evdev.events.KeyEvent.key_down:
                                pressed.add(code)
                                if (
                                    code in trigger_codes
                                    and modifier_codes.issubset(pressed)
                                ):
                                    _logger.debug("sgk_hotkey_triggered_evdev")
                                    if self._callback:
                                        self._callback()
                            elif key_event.keystate == evdev.events.KeyEvent.key_up:
                                pressed.discard(code)
                    except (OSError, BlockingIOError):
                        # Device disconnected
                        fds.pop(fd, None)

        except Exception as exc:
            _logger.error("sgk_evdev_loop_error", extra={"error": str(exc)})
        finally:
            for dev in keyboards:
                try:
                    dev.close()
                except Exception:
                    pass
