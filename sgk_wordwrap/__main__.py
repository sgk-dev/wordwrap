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
        version=f"%(prog)s 0.1.0",
    )
    return parser.parse_args()


def _sgk_install_service() -> None:
    import shutil
    from pathlib import Path

    service_src = Path(__file__).parent.parent / "packaging" / "sgk-wordwrap.service"
    service_dst = Path.home() / ".config" / "systemd" / "user" / "sgk-wordwrap.service"
    desktop_src = Path(__file__).parent.parent / "packaging" / "sgk-wordwrap.desktop"
    autostart_dst = Path.home() / ".config" / "autostart" / "sgk-wordwrap.desktop"

    service_dst.parent.mkdir(parents=True, exist_ok=True)
    autostart_dst.parent.mkdir(parents=True, exist_ok=True)

    if service_src.exists():
        shutil.copy2(service_src, service_dst)
        print(f"Installed: {service_dst}")
        print("Enable with: systemctl --user enable --now sgk-wordwrap")
    else:
        print("Warning: service file not found, skipping systemd setup")

    if desktop_src.exists():
        shutil.copy2(desktop_src, autostart_dst)
        print(f"Installed: {autostart_dst}")


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
