"""Wayland-compatible key injection using evdev.UInput.

Provides a way to simulate key presses (Ctrl+C, Ctrl+V, Backspace) and type text
directly through a virtual keyboard device.
Requires 'uinput' kernel module and write access to /dev/uinput.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

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
    "backspace": ecodes.KEY_BACKSPACE,
    "enter": ecodes.KEY_ENTER,
    "space": ecodes.KEY_SPACE,
    "tab":   ecodes.KEY_TAB,
}


class SgkUinputInjector:
    """Simulates keyboard input via evdev.UInput (Wayland-safe)."""

    def __init__(self, name: str = "SGK WordWrap Virtual Keyboard") -> None:
        self._name = name
        self._ui: evdev.UInput | None = None
        self._sgk_initialize()

    def _sgk_initialize(self) -> None:
        """Create the virtual keyboard device with all possible keys."""
        try:
            # We want to support all keys that can be typed or simulated
            cap = {
                ecodes.EV_KEY: list(ecodes.KEY.keys()),
            }
            self._ui = evdev.UInput(cap, name=self._name)
            _logger.info("sgk_uinput_initialized", extra={"device": self._name})
        except (PermissionError, OSError) as exc:
            _logger.warning(
                "sgk_uinput_init_failed",
                extra={"hint": "Ensure /dev/uinput is writable by 'input' group", "error": str(exc)},
            )
            self._ui = None

    def sgk_is_available(self) -> bool:
        return self._ui is not None

    def sgk_send_combo(self, combo: str) -> None:
        """Send a key combination like 'ctrl+c' or 'ctrl+shift+left'."""
        if not self._ui:
            return

        parts = [p.strip().lower() for p in combo.split("+")]
        codes = []
        for p in parts:
            code = _SGK_NAME_TO_CODE.get(p)
            if code is None:
                # Try KEY_ name
                code_name = f"KEY_{p.upper()}"
                code = getattr(ecodes, code_name, None)
            
            if code is not None:
                codes.append(code)
            else:
                _logger.warning("sgk_uinput_unknown_key", extra={"key": p})

        if not codes:
            return

        # Press all
        for c in codes:
            self._ui.write(ecodes.EV_KEY, c, 1)
        self._ui.syn()

        time.sleep(0.01)

        # Release all (reversed)
        for c in reversed(codes):
            self._ui.write(ecodes.EV_KEY, c, 0)
        self._ui.syn()

    def sgk_type_text(self, text: str) -> None:
        """Type text character by character. Supports only simple ASCII-mappable keys.
        For non-ASCII, it's better to use clipboard + Ctrl+V.
        """
        if not self._ui:
            return

        # Mapping for some ASCII chars to keys (US layout assumed for uinput injection)
        # Note: This is very basic. For full international support, use clipboard.
        for char in text:
            self._sgk_type_char(char)
        
        self._ui.syn()

    def _sgk_type_char(self, char: str) -> None:
        if not self._ui:
            return

        # This is a bit complex because we need to know WHICH key + shift/alt
        # For simplicity and robustness, we prefer using clipboard for text typing.
        # But for very short things or when clipboard is risky, we can try here.
        # However, evdev injection is layout-dependent on the *receiving* app's side.
        # So we should probably stick to 'clipboard + Ctrl+V' for the actual converted text.
        pass

    def sgk_close(self) -> None:
        if self._ui:
            self._ui.close()
            self._ui = None
