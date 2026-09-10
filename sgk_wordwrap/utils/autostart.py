"""XDG autostart entry management for WordWrap.

The source of truth for "launch on login" is a desktop file in
``~/.config/autostart/``. This module creates or removes it; the settings
dialog uses these helpers to back the "Launch on login" checkbox.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from sgk_wordwrap.utils.logger import sgk_get_logger

_logger = sgk_get_logger(__name__)

SGK_AUTOSTART_PATH = Path.home() / ".config" / "autostart" / "wordwrap.desktop"

_TEMPLATE = """\
[Desktop Entry]
Type=Application
Name=WordWrap
GenericName=Keyboard Layout Switcher
Comment=Fix text typed in the wrong keyboard layout
Exec={exec_cmd}
Icon=wordwrap
Categories=Utility;Accessibility;
Keywords=keyboard;layout;switch;punto;
Terminal=false
StartupNotify=false
X-GNOME-Autostart-enabled=true
X-GNOME-Autostart-Delay=3
"""


def sgk_default_exec_cmd() -> str:
    """Best-effort command that starts the daemon with its tray."""
    launcher = Path.home() / ".local" / "bin" / "sgk-wordwrap"
    if launcher.exists():
        return str(launcher)
    found = shutil.which("sgk-wordwrap")
    if found:
        return found
    return "sgk-wordwrap"


def sgk_is_autostart_enabled() -> bool:
    return SGK_AUTOSTART_PATH.is_file()


def sgk_set_autostart(enabled: bool, exec_cmd: str | None = None) -> bool:
    """Create or remove the autostart entry. Returns the resulting state."""
    try:
        if enabled:
            SGK_AUTOSTART_PATH.parent.mkdir(parents=True, exist_ok=True)
            content = _TEMPLATE.format(exec_cmd=exec_cmd or sgk_default_exec_cmd())
            SGK_AUTOSTART_PATH.write_text(content, encoding="utf-8")
            _logger.info("sgk_autostart_enabled", extra={"path": str(SGK_AUTOSTART_PATH)})
        else:
            SGK_AUTOSTART_PATH.unlink(missing_ok=True)
            _logger.info("sgk_autostart_disabled")
    except OSError as exc:
        _logger.error("sgk_autostart_error", extra={"error": str(exc)})
    return sgk_is_autostart_enabled()
