"""Sensitive-context detection (password managers, pinentry, blacklist).

On X11 the focused window's process / class / title come from xdotool. On
GNOME Wayland there is no active-window API available to a normal client, so
the detector reports "unknown" and the blacklist is best-effort only.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from sgk_wordwrap.utils.display_server import sgk_detect_display_server
from sgk_wordwrap.utils.logger import sgk_get_logger

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
    """Decides whether the focused context should be left alone."""

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

    def sgk_is_sensitive_context(
        self,
        process_name: str | None = None,
        window_class: str | None = None,
        window_title: str | None = None,
    ) -> bool:
        """Return True if current context should be skipped (password, blacklisted)."""
        if process_name:
            pname = process_name.lower()
            if pname in _SGK_SENSITIVE_PROCESSES or pname in self._extra_processes:
                _logger.debug("sgk_sensitive_process", extra={"proc": process_name})
                return True

        if window_class:
            wclass = window_class.lower()
            if wclass in _SGK_SENSITIVE_WINDOW_CLASSES or wclass in self._extra_classes:
                _logger.debug("sgk_sensitive_class", extra={"window_class": window_class})
                return True

        if window_title:
            for regex in self._title_regexes:
                if regex.search(window_title):
                    _logger.debug(
                        "sgk_sensitive_title",
                        extra={"title": window_title[:40]},
                    )
                    return True

        return False

    def sgk_get_active_window_info(self) -> tuple[str | None, str | None, str | None]:
        """Return (process_name, window_class, window_title) for the focused window.

        X11 only (xdotool). On Wayland every field is None.
        """
        if sgk_detect_display_server() == "x11":
            return self._sgk_get_info_x11()
        return None, None, None

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
                    process_name = Path(f"/proc/{pid_out}/comm").read_text().strip()
                except OSError:
                    pass

            return process_name, name_out or None, title_out or None
        except Exception:
            return None, None, None
