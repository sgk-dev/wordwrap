"""System tray icon for sgk-wordwrap.

PyQt6 QSystemTrayIcon with context menu:
  ✓ Enabled / Paused toggle
  → Layouts submenu (current layout indicator)
  → Settings...
  → Quit

Communicates with the main app via callback functions.
"""

from __future__ import annotations

from typing import Callable

from sgk_wordwrap.utils.logger import sgk_get_logger

_logger = sgk_get_logger(__name__)


class SgkTrayIcon:
    """System tray icon. Requires a running QApplication."""

    def __init__(
        self,
        on_pause_toggle: Callable[[], None],
        on_open_settings: Callable[[], None],
        on_quit: Callable[[], None],
        is_paused_getter: Callable[[], bool] | None = None,
    ) -> None:
        self._on_pause_toggle = on_pause_toggle
        self._on_open_settings = on_open_settings
        self._on_quit = on_quit
        self._is_paused_getter = is_paused_getter
        self._tray = None
        self._pause_action = None
        self._layout_menu = None
        self._state_timer = None
        self._paused = False

    def sgk_create(self) -> None:
        """Build and show the tray icon. Must be called from the Qt thread."""
        try:
            from PyQt6.QtGui import QColor, QIcon, QPixmap
            from PyQt6.QtWidgets import QMenu, QSystemTrayIcon

            # Create a simple colored icon (16x16 filled square)
            pixmap = QPixmap(16, 16)
            pixmap.fill(QColor("#4A90D9"))
            icon = QIcon(pixmap)

            self._tray = QSystemTrayIcon(icon)
            self._tray.setToolTip("sgk-wordwrap")

            # Left click on the icon toggles enabled/disabled.
            def _on_activated(reason) -> None:
                if reason == QSystemTrayIcon.ActivationReason.Trigger:
                    self._on_pause_toggle()

            self._tray.activated.connect(_on_activated)

            menu = QMenu()

            # Enabled / Paused toggle
            self._pause_action = menu.addAction("Enabled")
            self._pause_action.setCheckable(True)
            self._pause_action.setChecked(True)
            self._pause_action.triggered.connect(self._sgk_handle_pause_toggle)

            menu.addSeparator()

            # Layouts submenu
            self._layout_menu = menu.addMenu("Layouts")
            self._sgk_update_layout_menu([])

            menu.addSeparator()

            settings_action = menu.addAction("Settings...")
            settings_action.triggered.connect(self._on_open_settings)

            menu.addSeparator()

            quit_action = menu.addAction("Quit")
            quit_action.triggered.connect(self._on_quit)

            self._tray.setContextMenu(menu)
            self._tray.show()

            # Poll the app's enabled/disabled state so the icon stays in sync
            # even when toggled from the hotkey (a non-Qt thread).
            if self._is_paused_getter is not None:
                from PyQt6.QtCore import QTimer

                self._state_timer = QTimer()
                self._state_timer.setInterval(300)
                self._state_timer.timeout.connect(self._sgk_sync_state)
                self._state_timer.start()

            _logger.info("sgk_tray_created")

        except ImportError:
            _logger.warning("sgk_tray_pyqt6_missing", extra={"hint": "pip install PyQt6"})
        except Exception as exc:
            _logger.error("sgk_tray_create_error", extra={"error": str(exc)})

    def sgk_set_paused(self, paused: bool) -> None:
        self._paused = paused
        if self._pause_action:
            self._pause_action.setChecked(not paused)
            self._pause_action.setText("Paused" if paused else "Enabled")
        if self._tray:
            try:
                from PyQt6.QtGui import QColor, QIcon, QPixmap
                color = "#888888" if paused else "#4A90D9"
                pixmap = QPixmap(16, 16)
                pixmap.fill(QColor(color))
                self._tray.setIcon(QIcon(pixmap))
            except Exception:
                pass

    def sgk_update_layouts(self, layouts: list[str], current: str) -> None:
        """Refresh the layouts submenu to reflect current state."""
        self._sgk_update_layout_menu(layouts, current)

    def sgk_show_message(self, title: str, message: str, duration_ms: int = 3000) -> None:
        if self._tray:
            try:
                from PyQt6.QtWidgets import QSystemTrayIcon
                self._tray.showMessage(title, message,
                                       QSystemTrayIcon.MessageIcon.Information,
                                       duration_ms)
            except Exception:
                pass

    def sgk_destroy(self) -> None:
        if self._state_timer:
            try:
                self._state_timer.stop()
            except Exception:
                pass
        if self._tray:
            try:
                self._tray.hide()
            except Exception:
                pass

    def _sgk_handle_pause_toggle(self, checked: bool) -> None:
        self._on_pause_toggle()

    def _sgk_sync_state(self) -> None:
        if self._is_paused_getter is None:
            return
        try:
            paused = bool(self._is_paused_getter())
        except Exception:
            return
        if paused != self._paused:
            self.sgk_set_paused(paused)

    def _sgk_update_layout_menu(
        self, layouts: list[str], current: str = ""
    ) -> None:
        if self._layout_menu is None:
            return
        try:
            self._layout_menu.clear()
            if not layouts:
                self._layout_menu.addAction("(detecting...)")
                return
            for layout in layouts:
                marker = " ✓" if layout == current else ""
                self._layout_menu.addAction(f"{layout}{marker}")
        except Exception:
            pass
