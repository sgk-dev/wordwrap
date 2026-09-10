"""Application lifecycle: SgkApp.

Orchestrates all components:
  - Config loading
  - Display server detection
  - Hotkey manager (X11 or evdev backend)
  - asyncio event loop
  - GUI (Qt tray + config dialog) in a separate thread
  - Clean shutdown on SIGTERM/SIGINT
"""

from __future__ import annotations

import asyncio
import sys
import threading
from typing import Any

from sgk_wordwrap.core.hotkey_manager import SgkHotkeyManager
from sgk_wordwrap.core.layout_manager import SgkLayoutManager
from sgk_wordwrap.core.text_processor import SgkTextProcessor
from sgk_wordwrap.input.clipboard import SgkClipboard
from sgk_wordwrap.layouts.detector import SgkFieldDetector
from sgk_wordwrap.layouts.mapper import SgkLayoutMapper
from sgk_wordwrap.utils.config import SgkConfig
from sgk_wordwrap.utils.logger import sgk_configure_logging, sgk_get_logger

_logger = sgk_get_logger(__name__)


class SgkApp:
    """Top-level application object."""

    def __init__(
        self,
        log_level_override: str | None = None,
        no_gui: bool = False,
    ) -> None:
        self._log_level_override = log_level_override
        self._no_gui = no_gui

        self._config = SgkConfig()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._hotkey_manager: SgkHotkeyManager | None = None
        self._layout_manager: SgkLayoutManager | None = None
        self._tray = None
        self._qt_thread: threading.Thread | None = None
        self._qt_app = None
        self._stopped = False

    def _sgk_toggle_enabled(self) -> None:
        """Flip conversion on/off. Safe to call from any thread."""
        if not self._hotkey_manager:
            return
        if self._hotkey_manager.sgk_is_paused():
            self._hotkey_manager.sgk_resume()
            _logger.info("sgk_conversion_enabled")
        else:
            self._hotkey_manager.sgk_pause()
            _logger.info("sgk_conversion_disabled")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def sgk_start(self) -> None:
        """Bootstrap all components and enter the event loop (blocking)."""
        cfg = self._config.sgk_load()
        self._sgk_configure_logging(cfg)

        _logger.info("sgk_app_starting", extra={"version": "0.2.0"})

        # Initialise all components
        mapper = SgkLayoutMapper(
            custom_maps_dir=cfg.get("layouts", {}).get("custom_maps_dir")
        )
        mapper.sgk_load_maps()

        layout_manager = SgkLayoutManager()

        detector = SgkFieldDetector(
            extra_processes=cfg.get("blacklist", {}).get("processes", []),
            extra_window_classes=cfg.get("blacklist", {}).get("window_classes", []),
            title_patterns=cfg.get("blacklist", {}).get("window_titles_regex", []),
        )

        behavior = cfg.get("behavior", {})
        clipboard = SgkClipboard(
            action_delay_ms=behavior.get("action_delay_ms", 50),
            clipboard_settle_ms=behavior.get("clipboard_settle_ms", 80),
            paste_settle_ms=behavior.get("paste_settle_ms", 80),
        )

        hotkeys = cfg.get("hotkeys", {})
        self._hotkey_manager = SgkHotkeyManager(hotkeys)

        processor = SgkTextProcessor(
            clipboard=clipboard,
            layout_manager=layout_manager,
            mapper=mapper,
            detector=detector,
            max_text_length=behavior.get("max_text_length", 10000),
            fallback_to_word=behavior.get("fallback_to_word_on_no_selection", True),
            settle_ms=behavior.get("hotkey_settle_ms", 150),
            copy_settle_ms=behavior.get("copy_settle_ms", 120),
        )
        self._layout_manager = layout_manager

        # Set up asyncio loop
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        def _run_convert(terminal: bool) -> None:
            if self._loop:
                asyncio.run_coroutine_threadsafe(
                    processor.sgk_process(terminal=terminal), self._loop
                )

        self._hotkey_manager.sgk_set_handler(_run_convert)
        self._hotkey_manager.sgk_set_toggle_handler(self._sgk_toggle_enabled)
        self._hotkey_manager.sgk_start(self._loop)

        if not behavior.get("enabled_on_start", True):
            self._hotkey_manager.sgk_pause()

        # Start asyncio loop in a separate thread
        self._async_thread = threading.Thread(
            target=self._loop.run_forever, name="sgk-asyncio", daemon=True
        )
        self._async_thread.start()

        _logger.info(
            "sgk_app_ready",
            extra={"hotkeys": hotkeys, "no_gui": self._no_gui},
        )

        # Start GUI (blocks the main thread)
        if not self._no_gui:
            self._sgk_start_gui(cfg, layout_manager)
            if self._qt_app:
                try:
                    sys.exit(self._qt_app.exec())
                except SystemExit:
                    pass
                finally:
                    self.sgk_stop()
        else:
            # Headless mode: wait until stop
            try:
                while self._async_thread.is_alive():
                    self._async_thread.join(1.0)
            except KeyboardInterrupt:
                pass
            finally:
                self.sgk_stop()

    def sgk_stop(self) -> None:
        """Graceful shutdown: stop listener, close loop, destroy tray."""
        if self._stopped:
            return
        self._stopped = True
        _logger.info("sgk_app_stopping")

        if self._hotkey_manager:
            self._hotkey_manager.sgk_stop()

        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)

        if self._tray:
            try:
                self._tray.sgk_destroy()
            except Exception:
                pass

        if self._qt_app:
            try:
                self._qt_app.quit()
            except Exception:
                pass

        _logger.info("sgk_app_stopped")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _sgk_configure_logging(self, cfg: dict[str, Any]) -> None:
        log_cfg = cfg.get("logging", {})
        level = self._log_level_override or log_cfg.get("level", "INFO")
        sgk_configure_logging(
            level=level,
            log_file=log_cfg.get("file"),
            max_bytes=log_cfg.get("max_bytes", 1_048_576),
            backup_count=log_cfg.get("backup_count", 3),
        )

    def _sgk_start_gui(
        self, cfg: dict[str, Any], layout_manager: SgkLayoutManager
    ) -> None:
        """Start PyQt6 application in the main thread (Qt requires main thread)."""
        try:
            from PyQt6.QtWidgets import QApplication

            from sgk_wordwrap.gui.config_dialog import SgkConfigDialog
            from sgk_wordwrap.gui.tray import SgkTrayIcon

            self._qt_app = QApplication.instance() or QApplication(sys.argv)
            self._qt_app.setQuitOnLastWindowClosed(False)

            def _open_settings() -> None:
                dialog = SgkConfigDialog(
                    config_data=self._config.data,
                    on_save=self._sgk_on_settings_saved,
                )
                dialog.sgk_show()

            def _is_paused() -> bool:
                return bool(
                    self._hotkey_manager and self._hotkey_manager.sgk_is_paused()
                )

            self._tray = SgkTrayIcon(
                on_pause_toggle=self._sgk_toggle_enabled,
                on_open_settings=_open_settings,
                on_quit=self.sgk_stop,
                is_paused_getter=_is_paused,
            )
            self._tray.sgk_create()
            self._tray.sgk_set_paused(_is_paused())

            # Update layout indicator
            layouts = layout_manager.sgk_get_active_layouts()
            current = layout_manager.sgk_get_current_layout()
            self._tray.sgk_update_layouts(layouts, current)

            _logger.info("sgk_gui_started")

        except ImportError:
            _logger.warning(
                "sgk_gui_unavailable",
                extra={"hint": "Install PyQt6: pip install PyQt6"},
            )
        except Exception as exc:
            _logger.error("sgk_gui_start_error", extra={"error": str(exc)})

    def _sgk_on_settings_saved(self, new_config: dict[str, Any]) -> None:
        """Handle config changes from the settings dialog."""
        self._config.sgk_save(new_config)
        _logger.info("sgk_settings_saved")
        # Note: hotkey changes require restart; notify user
        if self._tray:
            self._tray.sgk_show_message(
                "sgk-wordwrap",
                "Settings saved. Restart to apply hotkey changes.",
            )
