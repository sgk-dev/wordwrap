"""Wayland/evdev global hotkey listener.

Reads keyboard events directly from /dev/input/event* devices.
Requires user in the 'input' group (or root).

udev rules shipped in packaging/99-sgk-uinput.rules.
"""

from __future__ import annotations

import collections
import glob
import os
import select
import threading
import time
from typing import Callable, Deque

from sgk_wordwrap.input.base import SgkInputBackend
from sgk_wordwrap.utils.logger import sgk_get_logger

_logger = sgk_get_logger(__name__)

# Max keys to keep in memory for "Scenario B" (last word recovery)
_SGK_MAX_BUFFER_SIZE = 50
_SGK_BUFFER_TIMEOUT = 5.0  # Clear buffer after 5s of inactivity

# For each modifier name: the set of acceptable keycodes (left OR right)
_SGK_MODIFIER_KEY_NAMES: dict[str, list[str]] = {
    "ctrl":  ["KEY_LEFTCTRL", "KEY_RIGHTCTRL"],
    "shift": ["KEY_LEFTSHIFT", "KEY_RIGHTSHIFT"],
    "alt":   ["KEY_LEFTALT", "KEY_RIGHTALT"],
    "super": ["KEY_LEFTMETA", "KEY_RIGHTMETA"],
}


def _sgk_keycode_to_char(keycode: int) -> str | None:
    """Very basic mapping for common keys in the buffer."""
    import evdev
    from evdev import ecodes

    _map = {
        ecodes.KEY_A: "a", ecodes.KEY_B: "b", ecodes.KEY_C: "c", ecodes.KEY_D: "d",
        ecodes.KEY_E: "e", ecodes.KEY_F: "f", ecodes.KEY_G: "g", ecodes.KEY_H: "h",
        ecodes.KEY_I: "i", ecodes.KEY_J: "j", ecodes.KEY_K: "k", ecodes.KEY_L: "l",
        ecodes.KEY_M: "m", ecodes.KEY_N: "n", ecodes.KEY_O: "o", ecodes.KEY_P: "p",
        ecodes.KEY_Q: "q", ecodes.KEY_R: "r", ecodes.KEY_S: "s", ecodes.KEY_T: "t",
        ecodes.KEY_U: "u", ecodes.KEY_V: "v", ecodes.KEY_W: "w", ecodes.KEY_X: "x",
        ecodes.KEY_Y: "y", ecodes.KEY_Z: "z",
        ecodes.KEY_SPACE: " ",
        ecodes.KEY_0: "0", ecodes.KEY_1: "1", ecodes.KEY_2: "2", ecodes.KEY_3: "3",
        ecodes.KEY_4: "4", ecodes.KEY_5: "5", ecodes.KEY_6: "6", ecodes.KEY_7: "7",
        ecodes.KEY_8: "8", ecodes.KEY_9: "9",
    }
    return _map.get(keycode)


def _sgk_parse_hotkey(hotkey_str: str) -> tuple[frozenset[str], str]:
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
        
        # Scenario B: last keys buffer
        self._key_buffer: Deque[tuple[int, float]] = collections.deque(maxlen=_SGK_MAX_BUFFER_SIZE)
        self._buffer_lock = threading.Lock()

    def sgk_get_last_word(self) -> str:
        """Retrieve the sequence of typed characters since last space/break."""
        with self._buffer_lock:
            now = time.monotonic()
            chars = []
            for code, t in reversed(self._key_buffer):
                if now - t > _SGK_BUFFER_TIMEOUT:
                    break
                char = _sgk_keycode_to_char(code)
                if char is None or char == " ":
                    break
                chars.append(char)
            return "".join(reversed(chars))

    def sgk_clear_buffer(self) -> None:
        """Clear the ring-buffer of typed keys."""
        with self._buffer_lock:
            self._key_buffer.clear()

    def sgk_is_available(self) -> bool:
        try:
            import evdev  # noqa: F401
            return len(self._sgk_find_keyboards()) > 0
        except ImportError:
            return False
        except PermissionError:
            _logger.warning(
                "sgk_evdev_no_permission",
                extra={"hint": "sudo usermod -aG input $USER, then reboot"},
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
        """Find all keyboard input devices using glob (evdev.list_devices() unreliable)."""
        import evdev
        keyboards = []
        for path in sorted(glob.glob("/dev/input/event*")):
            try:
                dev = evdev.InputDevice(path)
                caps = dev.capabilities()
                if (
                    evdev.ecodes.EV_KEY in caps
                    and evdev.ecodes.KEY_A in caps[evdev.ecodes.EV_KEY]
                ):
                    keyboards.append(dev)
                else:
                    dev.close()
            except (PermissionError, OSError):
                continue
            except Exception as exc:
                _logger.debug("sgk_evdev_device_skip", extra={"path": path, "error": str(exc)})
        return keyboards

    def _sgk_run_evdev_loop(self) -> None:
        keyboards = []
        try:
            import evdev

            keyboards = self._sgk_find_keyboards()
            if not keyboards:
                _logger.error("sgk_evdev_no_keyboards")
                return

            _logger.debug("sgk_evdev_keyboards_found", extra={"count": len(keyboards)})

            # Trigger keycode
            trigger_codes: set[int] = set()
            trigger_name = f"KEY_{self._trigger_key.upper()}"
            code = getattr(evdev.ecodes, trigger_name, None)
            if code is not None:
                trigger_codes.add(code)
            else:
                _logger.error("sgk_evdev_unknown_trigger_key", extra={"key": self._trigger_key})
                return

            # Modifier groups: list of sets — for each modifier, ANY code from the group suffices
            modifier_groups: list[set[int]] = []
            for mod_name in self._modifiers:
                group: set[int] = set()
                for key_name in _SGK_MODIFIER_KEY_NAMES.get(mod_name, []):
                    c = getattr(evdev.ecodes, key_name, None)
                    if c is not None:
                        group.add(c)
                if group:
                    modifier_groups.append(group)

            _logger.debug(
                "sgk_evdev_hotkey_codes",
                extra={"trigger": trigger_codes, "modifier_groups": [list(g) for g in modifier_groups]},
            )

            def _modifiers_active(pressed: set[int]) -> bool:
                """True if at least one key from each modifier group is pressed."""
                return all(bool(group & pressed) for group in modifier_groups)

            pressed: set[int] = set()
            stop_r = self._stop_pipe[0] if self._stop_pipe else None
            fds: dict[int, object] = {dev.fd: dev for dev in keyboards}
            if stop_r is not None:
                fds[stop_r] = None

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
                        for event in dev.read():  # type: ignore[union-attr]
                            if event.type != evdev.ecodes.EV_KEY:
                                continue
                            key_event = evdev.categorize(event)
                            keycode = key_event.scancode

                            if key_event.keystate == evdev.events.KeyEvent.key_down:
                                pressed.add(keycode)
                                if keycode in trigger_codes and _modifiers_active(pressed):
                                    _logger.debug("sgk_hotkey_triggered_evdev")
                                    if self._callback:
                                        self._callback()
                                else:
                                    # Scenario B: store in buffer if not a modifier and not hotkey
                                    # Also clear buffer on break keys (Enter, Esc)
                                    if keycode in (evdev.ecodes.KEY_ENTER, evdev.ecodes.KEY_ESC):
                                        self.sgk_clear_buffer()
                                    elif _sgk_keycode_to_char(keycode):
                                        with self._buffer_lock:
                                            self._key_buffer.append((keycode, time.monotonic()))
                            elif key_event.keystate in (
                                evdev.events.KeyEvent.key_up,
                                evdev.events.KeyEvent.key_hold,
                            ):
                                if key_event.keystate == evdev.events.KeyEvent.key_up:
                                    pressed.discard(keycode)
                    except (OSError, BlockingIOError):
                        fds.pop(fd, None)

        except Exception as exc:
            _logger.error("sgk_evdev_loop_error", extra={"error": str(exc)})
        finally:
            for dev in keyboards:
                try:
                    dev.close()  # type: ignore[union-attr]
                except Exception:
                    pass
