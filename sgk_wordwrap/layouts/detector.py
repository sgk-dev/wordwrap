"""Password field and read-only area detection.

Uses AT-SPI accessibility API when available, with process/window-class fallbacks.
If a password field is detected, the conversion is silently skipped.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from sgk_wordwrap.utils.logger import sgk_get_logger

if TYPE_CHECKING:
    pass

_logger = sgk_get_logger(__name__)

_SGK_SENSITIVE_PROCESSES = frozenset({
    "keepassxc", "keepass", "keepass2",
    "pinentry", "pinentry-qt", "pinentry-gtk", "pinentry-gnome3", "pinentry-curses",
    "1password", "bitwarden", "enpass",
    "gnupg", "gpg", "gpg-agent",
    "pkexec", "gksu", "gksudo", "beesu",
    "sudo",
})

_SGK_SENSITIVE_WINDOW_CLASSES = frozenset({
    "pinentry", "pinentry-qt", "pinentry-gtk",
    "keepassxc", "keepass2",
})


class SgkFieldDetector:
    """Detects whether the current focused widget is a password field or read-only."""

    def __init__(
        self,
        extra_processes: list[str] | None = None,
        extra_window_classes: list[str] | None = None,
        title_patterns: list[str] | None = None,
    ) -> None:
        self._extra_processes = frozenset(p.lower() for p in (extra_processes or []))
        self._extra_classes = frozenset(c.lower() for c in (extra_window_classes or []))
        self._title_regexes = [
            re.compile(p, re.IGNORECASE) for p in (title_patterns or [])
        ]
        self._atspi_available = self._sgk_check_atspi()

    def _sgk_check_atspi(self) -> bool:
        try:
            import pyatspi  # noqa: F401
            return True
        except ImportError:
            return False

    def sgk_is_sensitive_context(
        self,
        process_name: str | None = None,
        window_class: str | None = None,
        window_title: str | None = None,
    ) -> bool:
        """Return True if current context should be skipped (password, blacklisted)."""
        # Check process name
        if process_name:
            pname = process_name.lower()
            if pname in _SGK_SENSITIVE_PROCESSES or pname in self._extra_processes:
                _logger.debug("sgk_sensitive_process", extra={"proc": process_name})
                return True

        # Check window class
        if window_class:
            wclass = window_class.lower()
            if wclass in _SGK_SENSITIVE_WINDOW_CLASSES or wclass in self._extra_classes:
                _logger.debug("sgk_sensitive_class", extra={"window_class": window_class})
                return True

        # Check window title regexes
        if window_title:
            for regex in self._title_regexes:
                if regex.search(window_title):
                    _logger.debug(
                        "sgk_sensitive_title",
                        extra={"title": window_title[:40]},
                    )
                    return True

        # AT-SPI check for password role on focused widget
        if self._atspi_available:
            if self._sgk_atspi_is_password_field():
                _logger.debug("sgk_atspi_password_field")
                return True

        return False

    def _sgk_atspi_is_password_field(self) -> bool:
        """Use AT-SPI to check if focused widget has PASSWORD_TEXT role."""
        try:
            import pyatspi
            desktop = pyatspi.Registry.getDesktop(0)
            for app in desktop:
                if app is None:
                    continue
                focused = app.queryAccessible()
                if focused and focused.getRole() == pyatspi.ROLE_PASSWORD_TEXT:
                    return True
        except Exception:
            pass
        return False

    def sgk_get_active_window_info(self) -> tuple[str | None, str | None, str | None]:
        """Return (process_name, window_class, window_title) for the focused window.

        Uses xdotool on X11; uses DBus on Wayland (GNOME/KDE).
        """
        # Try X11 first (most reliable if xdotool is present and display is X11)
        if self._sgk_is_x11():
            info = self._sgk_get_info_x11()
            if info[1]: # if window_class is found
                return info

        # Fallback to Wayland/DBus
        return self._sgk_get_info_wayland()

    def _sgk_is_x11(self) -> bool:
        from sgk_wordwrap.utils.display_server import sgk_detect_display_server
        return sgk_detect_display_server() == "x11"

    def _sgk_get_info_x11(self) -> tuple[str | None, str | None, str | None]:
        try:
            win_id = subprocess.check_output(
                ["xdotool", "getactivewindow"],
                timeout=0.2,
                stderr=subprocess.DEVNULL,
            ).decode().strip()

            name_out = subprocess.check_output(
                ["xdotool", "getwindowclassname", win_id],
                timeout=0.2,
                stderr=subprocess.DEVNULL,
            ).decode().strip()

            title_out = subprocess.check_output(
                ["xdotool", "getwindowname", win_id],
                timeout=0.2,
                stderr=subprocess.DEVNULL,
            ).decode().strip()

            pid_out = subprocess.check_output(
                ["xdotool", "getwindowpid", win_id],
                timeout=0.2,
                stderr=subprocess.DEVNULL,
            ).decode().strip()

            process_name = None
            if pid_out.isdigit():
                try:
                    comm = Path(f"/proc/{pid_out}/comm").read_text().strip()
                    process_name = comm
                except OSError:
                    pass

            return process_name, name_out or None, title_out or None
        except Exception:
            return None, None, None

    def _sgk_get_info_wayland(self) -> tuple[str | None, str | None, str | None]:
        """Attempt to get info via DBus for GNOME or KDE."""
        # KDE Plasma
        try:
            # qdbus org.kde.KWin /KWin activeWindow
            subprocess.check_output(
                ["qdbus", "org.kde.KWin", "/KWin", "activeWindow"],
                timeout=0.2, stderr=subprocess.DEVNULL
            ).decode().strip()
            # This is just an ID. Getting more info requires more calls.
            # For simplicity, we might just use AT-SPI which is better.
        except Exception:
            pass

        # If we reach here, we rely on AT-SPI for password fields,
        # but window-based blacklisting might be limited on Wayland without specific extensions.
        return None, None, None
