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
from dataclasses import dataclass
from typing import Callable

from sgk_wordwrap.input.base import SgkInputBackend
from sgk_wordwrap.utils.logger import sgk_get_logger

_logger = sgk_get_logger(__name__)

# For each modifier name: the acceptable keycodes (left OR right).
_SGK_MODIFIER_KEY_NAMES: dict[str, list[str]] = {
    "ctrl":  ["KEY_LEFTCTRL", "KEY_RIGHTCTRL"],
    "shift": ["KEY_LEFTSHIFT", "KEY_RIGHTSHIFT"],
    "alt":   ["KEY_LEFTALT", "KEY_RIGHTALT"],
    "super": ["KEY_LEFTMETA", "KEY_RIGHTMETA"],
}

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
                _logger.debug(
                    "sgk_evdev_device_skip", extra={"path": path, "error": str(exc)}
                )
        return keyboards

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
        keyboards = []
        try:
            import evdev

            keyboards = self._sgk_find_keyboards()
            if not keyboards:
                _logger.error("sgk_evdev_no_keyboards")
                return

            mod_code_to_name, trigger_codes = self._sgk_build_code_maps(evdev)
            if not trigger_codes:
                _logger.error("sgk_evdev_no_valid_hotkeys")
                return

            pressed_mods: set[str] = set()
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
                            try:
                                self._sgk_handle_key_event(
                                    evdev, event, mod_code_to_name,
                                    trigger_codes, pressed_mods,
                                )
                            except Exception as exc:
                                # One bad event must not kill the listener.
                                _logger.error(
                                    "sgk_evdev_event_error", extra={"error": str(exc)}
                                )
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

    def _sgk_handle_key_event(
        self, evdev, event, mod_code_to_name, trigger_codes, pressed_mods
    ) -> None:
        key_event = evdev.categorize(event)
        keycode = key_event.scancode
        state = key_event.keystate

        if keycode in mod_code_to_name:
            mod_name = mod_code_to_name[keycode]
            if state == evdev.events.KeyEvent.key_down:
                pressed_mods.add(mod_name)
            elif state == evdev.events.KeyEvent.key_up:
                pressed_mods.discard(mod_name)
            return

        if state == evdev.events.KeyEvent.key_down and keycode in trigger_codes:
            name = _sgk_pick_hotkey(
                set(pressed_mods), trigger_codes[keycode], self._specs
            )
            if name and self._callback:
                _logger.debug("sgk_hotkey_triggered_evdev", extra={"hotkey": name})
                self._callback(name)
