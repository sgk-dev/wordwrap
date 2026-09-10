"""Entry point: python -m sgk_wordwrap or sgk-wordwrap CLI."""

from __future__ import annotations

import argparse
import shutil
import signal
import subprocess
import sys
from pathlib import Path

from sgk_wordwrap.utils.logger import sgk_get_logger
from sgk_wordwrap.utils.resources import sgk_desktop_entry, sgk_systemd_unit

_logger = sgk_get_logger(__name__)

_ICON_SRC = Path(__file__).parent / "gui" / "icon.png"

_APPS_DST = Path.home() / ".local" / "share" / "applications" / "wordwrap.desktop"
_ICON_DST = (
    Path.home()
    / ".local" / "share" / "icons" / "hicolor" / "256x256" / "apps" / "wordwrap.png"
)
_AUTOSTART_DST = Path.home() / ".config" / "autostart" / "wordwrap.desktop"
_SERVICE_DST = Path.home() / ".config" / "systemd" / "user" / "sgk-wordwrap.service"


def _sgk_exec_cmd() -> str:
    """Command the .desktop / service should run to start the daemon."""
    return shutil.which("sgk-wordwrap") or f"{sys.executable} -m sgk_wordwrap"


def _sgk_parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="sgk-wordwrap",
        description="Fix text typed in the wrong keyboard layout (GNOME Wayland)",
    )
    parser.add_argument(
        "--log-level",
        default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Override log level from config",
    )
    parser.add_argument(
        "--install-desktop",
        action="store_true",
        help="Add WordWrap to the applications menu (icon + .desktop) and exit",
    )
    parser.add_argument(
        "--install-service",
        action="store_true",
        help="Install the systemd user service + autostart + menu entry and exit",
    )
    parser.add_argument(
        "--no-gui",
        action="store_true",
        help="Run without system tray (headless mode)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="%(prog)s 0.3.1",
    )
    return parser.parse_args()


def _sgk_install_desktop() -> None:
    """Install the icon and the .desktop launcher into the applications menu."""
    for dst in (_APPS_DST, _ICON_DST):
        dst.parent.mkdir(parents=True, exist_ok=True)

    if _ICON_SRC.exists():
        shutil.copy2(_ICON_SRC, _ICON_DST)
        print(f"Installed: {_ICON_DST}")

    _APPS_DST.write_text(sgk_desktop_entry(_sgk_exec_cmd()), encoding="utf-8")
    print(f"Installed: {_APPS_DST}")

    for cmd in (
        ["update-desktop-database", str(_APPS_DST.parent)],
        ["gtk-update-icon-cache", "-f", "-t",
         str(Path.home() / ".local" / "share" / "icons" / "hicolor")],
    ):
        try:
            subprocess.run(cmd, check=False, capture_output=True, timeout=15)
        except (FileNotFoundError, subprocess.SubprocessError):
            pass
    print('Done. Look for "WordWrap" in the applications overview.')


def _sgk_install_service() -> None:
    _sgk_install_desktop()

    for dst in (_SERVICE_DST, _AUTOSTART_DST):
        dst.parent.mkdir(parents=True, exist_ok=True)

    _AUTOSTART_DST.write_text(
        sgk_desktop_entry(_sgk_exec_cmd(), autostart=True), encoding="utf-8"
    )
    print(f"Installed: {_AUTOSTART_DST}")

    _SERVICE_DST.write_text(sgk_systemd_unit(_sgk_exec_cmd()), encoding="utf-8")
    print(f"Installed: {_SERVICE_DST}")
    print("Enable with: systemctl --user enable --now sgk-wordwrap")


def main() -> None:
    args = _sgk_parse_args()

    if args.install_desktop:
        _sgk_install_desktop()
        sys.exit(0)

    if args.install_service:
        _sgk_install_service()
        sys.exit(0)

    from sgk_wordwrap.utils.single_instance import sgk_acquire_single_instance

    if not sgk_acquire_single_instance():
        print("WordWrap is already running.")
        sys.exit(0)

    from sgk_wordwrap.app import SgkApp

    app = SgkApp(log_level_override=args.log_level, no_gui=args.no_gui)

    def _handle_signal(signum: int, frame: object) -> None:
        _logger.info("sgk_signal_received", extra={"signal": signum})
        app.sgk_stop()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    app.sgk_start()


if __name__ == "__main__":
    main()
