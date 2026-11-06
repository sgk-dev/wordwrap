"""Wayland/evdev global hotkey listener.

Reads keyboard events directly from /dev/input/event* devices (requires the user
to be in the 'input' group). Supports several named hotkeys at once and fires a
callback with the name of whichever one matched. When two hotkeys share a
trigger key (e.g. Ctrl+F1 and Ctrl+Shift+F1), the most specific match wins.
"""

from __future__ import annotations

import glob
import os
import select
import threading
import time
from dataclasses import dataclass
from typing import Callable

from sgk_wordwrap.input.base import SGK_VIRTUAL_DEVICE_NAME, SgkInputBackend
from sgk_wordwrap.utils.logger import sgk_get_logger

_logger = sgk_get_logger(__name__)

# For each modifier name: the acceptable keycodes (left OR right).
_SGK_MODIFIER_KEY_NAMES: dict[str, list[str]] = {
    "ctrl":  ["KEY_LEFTCTRL", "KEY_RIGHTCTRL"],
    "shift": ["KEY_LEFTSHIFT", "KEY_RIGHTSHIFT"],
    "alt":   ["KEY_LEFTALT", "KEY_RIGHTALT"],
    "super": ["KEY_LEFTMETA", "KEY_RIGHTMETA"],
}

_SGK_RESCAN_S = 2.0

_SGK_MODIFIER_ALIASES: dict[str, str] = {
    "control": "ctrl",
    "primary": "ctrl",
    "meta": "super",
    "logo": "super",
    "win": "super",
}


@dataclass(frozen=True)
class _SgkHotkeySpec:
    name: str
    modifiers: frozenset[str]
    key: str


def _sgk_parse_hotkey(hotkey_str: str) -> tuple[frozenset[str], str]:
    """Parse ``ctrl+shift+f1`` or GNOME-style ``<Primary><Shift>F1``."""
    s = hotkey_str.replace("<", "+").replace(">", "+")
    parts = [p.strip().lower() for p in s.split("+") if p.strip()]
    if not parts:
        return frozenset(), ""
    key = parts[-1]
    mods = {
        _SGK_MODIFIER_ALIASES.get(p, p)
        for p in parts[:-1]
    }
    return frozenset(mods), key


def sgk_parse_hotkey(hotkey_str: str) -> tuple[frozenset[str], str]:
    return _sgk_parse_hotkey(hotkey_str)


def sgk_hotkey_is_valid(hotkey_str: str) -> bool:
    mods, key = _sgk_parse_hotkey(hotkey_str)
    if not key or not mods <= _SGK_MODIFIER_KEY_NAMES.keys():
        return False
    if _SGK_MODIFIER_ALIASES.get(key, key) in _SGK_MODIFIER_KEY_NAMES:
        return False
    try:
        from evdev import ecodes
    except ImportError:
        return True
    return hasattr(ecodes, f"KEY_{key.upper()}")


def _sgk_pick_hotkey(
    pressed_mods: set[str],
    trigger_key: str,
    specs: list[_SgkHotkeySpec],
) -> str | None:
    """Return the name of the most specific hotkey satisfied by the current
    modifier state, or None. "Most specific" = most modifiers required.
    """
    best: _SgkHotkeySpec | None = None
    for spec in specs:
        if spec.key != trigger_key:
            continue
        if not spec.modifiers.issubset(pressed_mods):
            continue
        if best is None or len(spec.modifiers) > len(best.modifiers):
            best = spec
    return best.name if best else None


class SgkEvdevHotkeyListener(SgkInputBackend):
    """Global hotkey listener using Linux evdev (Wayland-compatible)."""

    def __init__(self, hotkeys: dict[str, str]) -> None:
        self._hotkeys = dict(hotkeys)
        self._specs: list[_SgkHotkeySpec] = []
        for name, combo in self._hotkeys.items():
            mods, key = _sgk_parse_hotkey(combo)
            if key:
                self._specs.append(_SgkHotkeySpec(name, mods, key))
        self._callback: Callable[[str], None] | None = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._stop_pipe: tuple[int, int] | None = None
        self._pressed_codes: set[int] = set()
        self._mod_code_to_name: dict[int, str] = {}

    # -- SgkInputBackend ------------------------------------------------

    def sgk_is_available(self) -> bool:
        try:
            import evdev  # noqa: F401
        except ImportError:
            return False
        try:
            kbds = self._sgk_find_keyboards()
        except PermissionError:
            _logger.warning(
                "sgk_evdev_no_permission",
                extra={"hint": "sudo usermod -aG input $USER, then re-login"},
            )
            return False
        for dev in kbds:
            try:
                dev.close()
            except Exception:
                pass
        return len(kbds) > 0

    def sgk_modifiers_held(self) -> bool:
        return bool(self._pressed_codes)

    def sgk_start(self, on_hotkey: Callable[[str], None]) -> None:
        self._callback = on_hotkey
        self._running = True
        self._stop_pipe = os.pipe()
        self._thread = threading.Thread(
            target=self._sgk_run_loop, name="sgk-evdev", daemon=True
        )
        self._thread.start()
        _logger.info(
            "sgk_evdev_listener_started",
            extra={"hotkeys": self._hotkeys},
        )

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
            for fd in self._stop_pipe:
                try:
                    os.close(fd)
                except OSError:
                    pass
            self._stop_pipe = None
        _logger.info("sgk_evdev_listener_stopped")

    # -- internals ----------------------------------------------------

    def _sgk_find_keyboards(self) -> list:
        keyboards = []
        for path in sorted(glob.glob("/dev/input/event*")):
            dev = self._sgk_open_keyboard(path)
            if dev is not None:
                keyboards.append(dev)
        return keyboards

    @staticmethod
    def _sgk_open_keyboard(path: str):
        import evdev

        try:
            dev = evdev.InputDevice(path)
        except (PermissionError, OSError):
            return None
        except Exception as exc:
            _logger.debug("sgk_evdev_device_skip", extra={"path": path, "error": str(exc)})
            return None
        try:
            caps = dev.capabilities()
            if (
                getattr(dev, "name", "") != SGK_VIRTUAL_DEVICE_NAME
                and evdev.ecodes.EV_KEY in caps
                and evdev.ecodes.KEY_A in caps[evdev.ecodes.EV_KEY]
            ):
                return dev
        except Exception as exc:
            _logger.debug("sgk_evdev_device_skip", extra={"path": path, "error": str(exc)})
        try:
            dev.close()
        except Exception:
            pass
        return None

    def _sgk_build_code_maps(self, evdev):
        """Build keycode→modifier-name and trigger-name→keycode lookups."""
        mod_code_to_name: dict[int, str] = {}
        for mod_name, key_names in _SGK_MODIFIER_KEY_NAMES.items():
            for kn in key_names:
                code = getattr(evdev.ecodes, kn, None)
                if code is not None:
                    mod_code_to_name[code] = mod_name

        trigger_codes: dict[int, str] = {}
        for spec in self._specs:
            code = getattr(evdev.ecodes, f"KEY_{spec.key.upper()}", None)
            if code is None:
                _logger.error(
                    "sgk_evdev_unknown_trigger_key", extra={"key": spec.key}
                )
                continue
            trigger_codes[code] = spec.key
        return mod_code_to_name, trigger_codes

    def _sgk_run_loop(self) -> None:
        fds: dict[int, object] = {}
        try:
            import evdev

            keyboards = self._sgk_find_keyboards()
            fds = {dev.fd: dev for dev in keyboards}
            if not keyboards:
                _logger.error("sgk_evdev_no_keyboards")
                return

            mod_code_to_name, trigger_codes = self._sgk_build_code_maps(evdev)
            if not trigger_codes:
                _logger.error("sgk_evdev_no_valid_hotkeys")
                return
            self._mod_code_to_name = mod_code_to_name

            pressed = self._pressed_codes
            pressed.clear()
            stop_r = self._stop_pipe[0] if self._stop_pipe else None
            seen_paths = {
                p for p in glob.glob("/dev/input/event*") if os.access(p, os.R_OK)
            }
            last_scan = time.monotonic()

            while self._running:
                watch = list(fds.keys()) + ([stop_r] if stop_r is not None else [])
                try:
                    readable, _, _ = select.select(watch, [], [], 1.0)
                except (ValueError, OSError):
                    break

                for fd in readable:
                    if fd == stop_r:
                        return
                    dev = fds.get(fd)
                    if dev is None:
                        continue
                    if not self._sgk_read_device(
                        evdev, dev, mod_code_to_name, trigger_codes, pressed
                    ):
                        fds.pop(fd, None)
                        seen_paths.discard(getattr(dev, "path", None))
                        pressed.clear()
                        self._sgk_close_device(dev)
                        _logger.info(
                            "sgk_evdev_keyboard_lost",
                            extra={"path": getattr(dev, "path", None), "left": len(fds)},
                        )

                if time.monotonic() - last_scan >= _SGK_RESCAN_S:
                    last_scan = time.monotonic()
                    self._sgk_rescan(fds, seen_paths)
        except Exception as exc:
            _logger.error("sgk_evdev_loop_error", extra={"error": str(exc)})
        finally:
            for dev in fds.values():
                self._sgk_close_device(dev)

    def _sgk_read_device(self, evdev, dev, mod_code_to_name, trigger_codes, pressed) -> bool:
        try:
            for event in dev.read():
                if event.type != evdev.ecodes.EV_KEY:
                    continue
                try:
                    self._sgk_handle_key_event(
                        evdev, event, mod_code_to_name, trigger_codes, pressed,
                    )
                except Exception as exc:
                    _logger.error("sgk_evdev_event_error", extra={"error": str(exc)})
        except BlockingIOError:
            return True
        except OSError:
            return False
        return True

    def _sgk_rescan(self, fds: dict[int, object], seen_paths: set) -> None:
        current = set(glob.glob("/dev/input/event*"))
        open_paths = {getattr(d, "path", None) for d in fds.values()}
        seen_paths.intersection_update(current)
        for path in sorted(current - seen_paths):
            if path in open_paths:
                seen_paths.add(path)
                continue
            if not os.access(path, os.R_OK):
                continue
            seen_paths.add(path)
            dev = self._sgk_open_keyboard(path)
            if dev is not None:
                fds[dev.fd] = dev
                _logger.info("sgk_evdev_keyboard_added", extra={"path": path})

    @staticmethod
    def _sgk_close_device(dev) -> None:
        try:
            dev.close()
        except Exception:
            pass

    def _sgk_handle_key_event(
        self, evdev, event, mod_code_to_name, trigger_codes, pressed_codes
    ) -> None:
        key_event = evdev.categorize(event)
        keycode = key_event.scancode
        state = key_event.keystate

        if keycode in mod_code_to_name:
            if state == evdev.events.KeyEvent.key_down:
                pressed_codes.add(keycode)
            elif state == evdev.events.KeyEvent.key_up:
                pressed_codes.discard(keycode)
            return

        if state == evdev.events.KeyEvent.key_down and keycode in trigger_codes:
            pressed_mods = {mod_code_to_name[c] for c in pressed_codes if c in mod_code_to_name}
            name = _sgk_pick_hotkey(pressed_mods, trigger_codes[keycode], self._specs)
            if name and self._callback:
                _logger.debug("sgk_hotkey_triggered_evdev", extra={"hotkey": name})
                self._callback(name)
