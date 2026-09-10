"""Wayland-compatible key injection using evdev.UInput.

Simulates key combos (Ctrl+V, Ctrl+Shift+V, Ctrl+Shift+Left, Backspace) through a
virtual keyboard device. Requires the 'uinput' kernel module and write access to
/dev/uinput (membership in the 'input' group).

Note: this injector deliberately does NOT type arbitrary text. On Wayland/Mutter
`wtype` is unavailable and keycode-level typing is layout-dependent, so converted
text is always delivered via clipboard + Ctrl+V (see SgkClipboard).
"""

from __future__ import annotations

import time

import evdev
from evdev import ecodes

from sgk_wordwrap.utils.logger import sgk_get_logger

_logger = sgk_get_logger(__name__)

# Mapping from common names to evdev KEY_* codes
_SGK_NAME_TO_CODE: dict[str, int] = {
    "ctrl":  ecodes.KEY_LEFTCTRL,
    "shift": ecodes.KEY_LEFTSHIFT,
    "alt":   ecodes.KEY_LEFTALT,
    "super": ecodes.KEY_LEFTMETA,
    "logo":  ecodes.KEY_LEFTMETA,
    "meta":  ecodes.KEY_LEFTMETA,
    "left":  ecodes.KEY_LEFT,
    "right": ecodes.KEY_RIGHT,
    "up":    ecodes.KEY_UP,
    "down":  ecodes.KEY_DOWN,
    "home":  ecodes.KEY_HOME,
    "end":   ecodes.KEY_END,
    "backspace": ecodes.KEY_BACKSPACE,
    "delete": ecodes.KEY_DELETE,
    "enter": ecodes.KEY_ENTER,
    "space": ecodes.KEY_SPACE,
    "tab":   ecodes.KEY_TAB,
}

# Delay between the press phase and the release phase of a combo.
_SGK_HOLD_S = 0.012


def _sgk_capabilities() -> list[int]:
    """Explicit key list for the virtual device.

    Passing the full ``ecodes.KEY`` map to ``evdev.UInput`` fails with EINVAL on
    this kernel, so declare only the keys any combo can realistically use.
    """
    codes: set[int] = set(_SGK_NAME_TO_CODE.values())
    for name in list("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"):
        codes.add(getattr(ecodes, f"KEY_{name}"))
    for i in range(1, 13):
        codes.add(getattr(ecodes, f"KEY_F{i}"))
    codes.add(ecodes.KEY_RIGHTCTRL)
    codes.add(ecodes.KEY_RIGHTSHIFT)
    return sorted(codes)


class SgkUinputInjector:
    """Simulates keyboard combos via evdev.UInput (Wayland-safe)."""

    def __init__(
        self,
        name: str = "SGK WordWrap Virtual Keyboard",
        ui: object | None = "auto",
    ) -> None:
        """`ui` may be an injected device (tests) or None to force unavailable.
        Left at the "auto" sentinel, a real evdev.UInput is created.
        """
        self._name = name
        if ui == "auto":
            self._ui = self._sgk_create_device()
        else:
            self._ui = ui

    def _sgk_create_device(self):
        try:
            cap = {ecodes.EV_KEY: _sgk_capabilities()}
            dev = evdev.UInput(cap, name=self._name)
            _logger.info("sgk_uinput_initialized", extra={"device": self._name})
            return dev
        except (PermissionError, OSError) as exc:
            _logger.warning(
                "sgk_uinput_init_failed",
                extra={
                    "hint": "Ensure /dev/uinput is writable by the 'input' group",
                    "error": str(exc),
                },
            )
            return None

    def sgk_is_available(self) -> bool:
        return self._ui is not None

    def _sgk_resolve(self, name: str) -> int | None:
        code = _SGK_NAME_TO_CODE.get(name)
        if code is None:
            code = getattr(ecodes, f"KEY_{name.upper()}", None)
        if code is None:
            _logger.warning("sgk_uinput_unknown_key", extra={"key": name})
        return code

    def _sgk_emit_combo(self, codes: list[int]) -> None:
        if not self._ui or not codes:
            return
        for c in codes:
            self._ui.write(ecodes.EV_KEY, c, 1)
        self._ui.syn()
        time.sleep(_SGK_HOLD_S)
        for c in reversed(codes):
            self._ui.write(ecodes.EV_KEY, c, 0)
        self._ui.syn()

    def sgk_send_combo(self, combo: str) -> None:
        """Send a key combination like 'ctrl+v' or 'ctrl+shift+left'."""
        if not self._ui:
            return
        parts = [p.strip().lower() for p in combo.split("+") if p.strip()]
        codes = [c for c in (self._sgk_resolve(p) for p in parts) if c is not None]
        self._sgk_emit_combo(codes)

    def sgk_paste(self, shift: bool = False) -> None:
        """Send the paste shortcut: Ctrl+V, or Ctrl+Shift+V for terminals."""
        if not self._ui:
            return
        codes = [ecodes.KEY_LEFTCTRL]
        if shift:
            codes.append(ecodes.KEY_LEFTSHIFT)
        codes.append(ecodes.KEY_V)
        self._sgk_emit_combo(codes)

    def sgk_close(self) -> None:
        if self._ui:
            try:
                self._ui.close()
            except Exception:
                pass
            self._ui = None
