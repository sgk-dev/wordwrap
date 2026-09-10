"""Entry point: python -m sgk_wordwrap or sgk-wordwrap CLI."""

from __future__ import annotations

import argparse
import signal
import sys

from sgk_wordwrap.utils.logger import sgk_get_logger

_logger = sgk_get_logger(__name__)


def _sgk_parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="sgk-wordwrap",
        description="Automatic keyboard layout switcher for Linux",
    )
    parser.add_argument(
        "--log-level",
        default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Override log level from config",
    )
    parser.add_argument(
        "--install-service",
        action="store_true",
        help="Install systemd user service and exit",
    )
    parser.add_argument(
        "--no-gui",
        action="store_true",
        help="Run without system tray (headless mode)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="%(prog)s 0.3.0",
    )
    return parser.parse_args()


def _sgk_install_service() -> None:
    import shutil
    from pathlib import Path

    root = Path(__file__).parent.parent
    service_src = root / "packaging" / "sgk-wordwrap.service"
    desktop_src = root / "packaging" / "wordwrap.desktop"
    icon_src = Path(__file__).parent / "gui" / "icon.png"

    service_dst = Path.home() / ".config" / "systemd" / "user" / "sgk-wordwrap.service"
    autostart_dst = Path.home() / ".config" / "autostart" / "wordwrap.desktop"
    apps_dst = Path.home() / ".local" / "share" / "applications" / "wordwrap.desktop"
    icon_dst = (
        Path.home()
        / ".local" / "share" / "icons" / "hicolor" / "256x256" / "apps" / "wordwrap.png"
    )

    for path in (service_dst, autostart_dst, apps_dst, icon_dst):
        path.parent.mkdir(parents=True, exist_ok=True)

    if service_src.exists():
        shutil.copy2(service_src, service_dst)
        print(f"Installed: {service_dst}")
        print("Enable with: systemctl --user enable --now sgk-wordwrap")
    else:
        print("Warning: service file not found, skipping systemd setup")

    if icon_src.exists():
        shutil.copy2(icon_src, icon_dst)
        print(f"Installed: {icon_dst}")

    if desktop_src.exists():
        shutil.copy2(desktop_src, autostart_dst)
        shutil.copy2(desktop_src, apps_dst)
        print(f"Installed: {autostart_dst}")
        print(f"Installed: {apps_dst}")


def main() -> None:
    args = _sgk_parse_args()

    if args.install_service:
        _sgk_install_service()
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
