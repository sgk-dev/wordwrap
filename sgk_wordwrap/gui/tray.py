"""System tray icon for WordWrap.

PyQt6 QSystemTrayIcon with a context menu:
  - Enable / disable toggle (also on left-click)
  - Settings...
  - About  (author, version, GitHub / donate links)
  - Quit

Menu items carry standard freedesktop theme icons. The tray icon itself has a
colour and a monochrome variant, chosen by ``ui.tray_icon_style``.
Communicates with the main app via callback functions.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from sgk_wordwrap import SGK_DONATE_URL, SGK_GITHUB_URL, __author__, __version__
from sgk_wordwrap.gui.i18n import sgk_normalize_lang, sgk_tr
from sgk_wordwrap.utils.logger import sgk_get_logger

_logger = sgk_get_logger(__name__)

_ICON_COLOR = Path(__file__).parent / "icon.png"
_ICON_MONO = Path(__file__).parent / "icon-mono.png"


def _sgk_icon_path(style: str) -> Path:
    return _ICON_MONO if style == "mono" and _ICON_MONO.exists() else _ICON_COLOR


def _sgk_make_icon(paused: bool, style: str = "color"):
    """Return a QIcon: the logo, dimmed when paused. Falls back to a dot."""
    from PyQt6.QtGui import QColor, QIcon, QPainter, QPixmap

    path = _sgk_icon_path(style)
    if path.exists():
        pm = QPixmap(str(path))
        if paused and not pm.isNull():
            dim = QPixmap(pm.size())
            dim.fill(QColor(0, 0, 0, 0))
            p = QPainter(dim)
            p.setOpacity(0.35)
            p.drawPixmap(0, 0, pm)
            p.end()
            pm = dim
        if not pm.isNull():
            return QIcon(pm)

    pm = QPixmap(16, 16)
    pm.fill(QColor("#888888" if paused else "#4A90D9"))
    return QIcon(pm)


def _sgk_theme_icon(name: str):
    from PyQt6.QtGui import QIcon

    return QIcon.fromTheme(name)


class SgkTrayIcon:
    """System tray icon. Requires a running QApplication."""

    def __init__(
        self,
        on_pause_toggle: Callable[[], None],
        on_open_settings: Callable[[], None],
        on_quit: Callable[[], None],
        is_paused_getter: Callable[[], bool] | None = None,
        lang: str = "en",
        icon_style: str = "color",
    ) -> None:
        self._on_pause_toggle = on_pause_toggle
        self._on_open_settings = on_open_settings
        self._on_quit = on_quit
        self._is_paused_getter = is_paused_getter
        self._lang = sgk_normalize_lang(lang)
        self._icon_style = icon_style if icon_style in ("color", "mono") else "color"
        self._tray = None
        self._menu = None
        self._pause_action = None
        self._settings_action = None
        self._about_action = None
        self._quit_action = None
        self._state_timer = None
        self._paused = False

    def sgk_create(self) -> None:
        """Build and show the tray icon. Must be called from the Qt thread."""
        try:
            from PyQt6.QtWidgets import QMenu, QSystemTrayIcon

            self._tray = QSystemTrayIcon(
                _sgk_make_icon(paused=False, style=self._icon_style)
            )
            self._tray.setToolTip(sgk_tr("tray.tooltip", self._lang))

            def _on_activated(reason) -> None:
                if reason == QSystemTrayIcon.ActivationReason.Trigger:
                    self._on_pause_toggle()

            self._tray.activated.connect(_on_activated)

            self._menu = QMenu()

            self._pause_action = self._menu.addAction("")
            self._pause_action.setCheckable(True)
            self._pause_action.setChecked(True)
            self._pause_action.triggered.connect(self._sgk_handle_pause_toggle)

            self._menu.addSeparator()

            self._settings_action = self._menu.addAction("")
            self._settings_action.setIcon(_sgk_theme_icon("preferences-system"))
            self._settings_action.triggered.connect(self._on_open_settings)

            self._about_action = self._menu.addAction("")
            self._about_action.setIcon(_sgk_theme_icon("help-about"))
            self._about_action.triggered.connect(self._sgk_show_about)

            self._menu.addSeparator()

            self._quit_action = self._menu.addAction("")
            self._quit_action.setIcon(_sgk_theme_icon("application-exit"))
            self._quit_action.triggered.connect(self._on_quit)

            self._tray.setContextMenu(self._menu)
            self._sgk_retranslate()
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

    def sgk_apply_ui(self, lang: str | None = None, icon_style: str | None = None) -> None:
        """Re-localise the menu and/or swap the icon variant at runtime."""
        if lang is not None:
            self._lang = sgk_normalize_lang(lang)
        if icon_style in ("color", "mono"):
            self._icon_style = icon_style
        self._sgk_retranslate()
        self.sgk_set_paused(self._paused)

    def sgk_set_paused(self, paused: bool) -> None:
        self._paused = paused
        if self._pause_action:
            self._pause_action.setChecked(not paused)
        self._sgk_retranslate()
        if self._tray:
            try:
                self._tray.setIcon(
                    _sgk_make_icon(paused=paused, style=self._icon_style)
                )
                key = "tray.tooltip_paused" if paused else "tray.tooltip"
                self._tray.setToolTip(sgk_tr(key, self._lang))
            except Exception:
                pass

    def sgk_show_message(self, title: str, message: str, duration_ms: int = 3000) -> None:
        if self._tray:
            try:
                from PyQt6.QtWidgets import QSystemTrayIcon
                self._tray.showMessage(
                    title,
                    message,
                    QSystemTrayIcon.MessageIcon.Information,
                    duration_ms,
                )
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

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _sgk_retranslate(self) -> None:
        if not self._pause_action:
            return
        try:
            paused_label = "tray.paused" if self._paused else "tray.enabled"
            self._pause_action.setText(sgk_tr(paused_label, self._lang))
            self._pause_action.setIcon(
                _sgk_theme_icon(
                    "media-playback-start" if self._paused else "media-playback-pause"
                )
            )
            self._settings_action.setText(sgk_tr("tray.settings", self._lang))
            self._about_action.setText(sgk_tr("tray.about", self._lang))
            self._quit_action.setText(sgk_tr("tray.quit", self._lang))
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

    def _sgk_show_about(self) -> None:
        try:
            from PyQt6.QtCore import QUrl
            from PyQt6.QtGui import QDesktopServices
            from PyQt6.QtWidgets import (
                QDialog,
                QDialogButtonBox,
                QHBoxLayout,
                QLabel,
                QPushButton,
                QVBoxLayout,
            )

            lang = self._lang
            dlg = QDialog()
            dlg.setWindowTitle(sgk_tr("about.title", lang))
            dlg.setMinimumWidth(380)

            layout = QVBoxLayout(dlg)

            title = QLabel("<b>WordWrap</b>")
            title.setStyleSheet("font-size: 16px;")
            layout.addWidget(title)
            layout.addWidget(QLabel(sgk_tr("about.tagline", lang)))
            layout.addWidget(
                QLabel(f"{sgk_tr('about.version', lang)}: {__version__}")
            )
            layout.addWidget(
                QLabel(f"{sgk_tr('about.author', lang)}: {__author__}")
            )

            thanks = QLabel(sgk_tr("about.thanks", lang))
            thanks.setWordWrap(True)
            thanks.setStyleSheet("color: palette(mid); margin-top: 6px;")
            layout.addWidget(thanks)

            links = QHBoxLayout()
            star_btn = QPushButton(sgk_tr("about.star", lang))
            star_btn.clicked.connect(
                lambda: QDesktopServices.openUrl(QUrl(SGK_GITHUB_URL))
            )
            donate_btn = QPushButton(sgk_tr("about.donate", lang))
            donate_btn.clicked.connect(
                lambda: QDesktopServices.openUrl(QUrl(SGK_DONATE_URL))
            )
            links.addWidget(star_btn)
            links.addWidget(donate_btn)
            layout.addLayout(links)

            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
            buttons.button(QDialogButtonBox.StandardButton.Close).setText(
                sgk_tr("about.close", lang)
            )
            buttons.rejected.connect(dlg.reject)
            buttons.accepted.connect(dlg.accept)
            layout.addWidget(buttons)

            dlg.exec()
        except Exception as exc:
            _logger.error("sgk_about_error", extra={"error": str(exc)})
