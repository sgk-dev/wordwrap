"""Settings dialog for WordWrap.

A tabbed PyQt6 QDialog:
  - General  (interface language, launch on login, monochrome tray icon)
  - Hotkeys
  - Blacklist (blocked processes)
  - Behavior
"""

from __future__ import annotations

from typing import Any, Callable

from sgk_wordwrap.gui.i18n import (
    SGK_LANGUAGE_NAMES,
    SGK_LANGUAGES,
    sgk_normalize_lang,
    sgk_tr,
)
from sgk_wordwrap.utils.autostart import sgk_is_autostart_enabled, sgk_set_autostart
from sgk_wordwrap.utils.logger import sgk_get_logger

_logger = sgk_get_logger(__name__)


class SgkConfigDialog:
    """Settings window. Call sgk_show() to open it."""

    def __init__(
        self,
        config_data: dict[str, Any],
        on_save: Callable[[dict[str, Any]], None],
        on_ui_changed: Callable[[str, str], None] | None = None,
    ) -> None:
        self._config = config_data
        self._on_save = on_save
        self._on_ui_changed = on_ui_changed
        self._lang = sgk_normalize_lang(config_data.get("ui", {}).get("language", "en"))

    def sgk_show(self) -> None:
        """Create and show the settings dialog (blocking modal)."""
        try:
            self._sgk_build_and_exec()
        except ImportError:
            _logger.warning("sgk_dialog_pyqt6_missing")
        except Exception as exc:
            _logger.error("sgk_dialog_error", extra={"error": str(exc)})

    def _tr(self, key: str) -> str:
        return sgk_tr(key, self._lang)

    def _sgk_build_and_exec(self) -> None:
        from PyQt6.QtWidgets import (
            QCheckBox,
            QComboBox,
            QDialog,
            QDialogButtonBox,
            QFormLayout,
            QGroupBox,
            QHBoxLayout,
            QLabel,
            QLineEdit,
            QListWidget,
            QPushButton,
            QSpinBox,
            QTabWidget,
            QVBoxLayout,
            QWidget,
        )

        ui_cfg = self._config.get("ui", {})
        hotkeys = self._config.get("hotkeys", {})
        behavior = self._config.get("behavior", {})

        dialog = QDialog()
        dialog.setWindowTitle(self._tr("cfg.title"))
        dialog.setMinimumWidth(480)

        tabs = QTabWidget()

        # ---- Tab: General ----
        gen_tab = QWidget()
        gen_layout = QFormLayout(gen_tab)

        lang_combo = QComboBox()
        for code in SGK_LANGUAGES:
            lang_combo.addItem(SGK_LANGUAGE_NAMES.get(code, code), code)
        cur_idx = lang_combo.findData(self._lang)
        lang_combo.setCurrentIndex(cur_idx if cur_idx >= 0 else 0)
        gen_layout.addRow(self._tr("cfg.language"), lang_combo)

        autostart_cb = QCheckBox()
        autostart_cb.setChecked(sgk_is_autostart_enabled())
        gen_layout.addRow(self._tr("cfg.autostart"), autostart_cb)

        mono_cb = QCheckBox()
        mono_cb.setChecked(ui_cfg.get("tray_icon_style", "color") == "mono")
        gen_layout.addRow(self._tr("cfg.mono_icon"), mono_cb)

        tabs.addTab(gen_tab, self._tr("cfg.tab.general"))

        # ---- Tab: Hotkeys ----
        hk_tab = QWidget()
        hk_layout = QFormLayout(hk_tab)
        convert_edit = QLineEdit(hotkeys.get("convert", "ctrl+f1"))
        terminal_edit = QLineEdit(hotkeys.get("convert_terminal", "ctrl+shift+f1"))
        last_word_edit = QLineEdit(hotkeys.get("convert_last_word", "ctrl+f2"))
        toggle_edit = QLineEdit(hotkeys.get("toggle", "ctrl+pause"))
        hk_layout.addRow(self._tr("cfg.hotkey.convert"), convert_edit)
        hk_layout.addRow(self._tr("cfg.hotkey.convert_terminal"), terminal_edit)
        hk_layout.addRow(self._tr("cfg.hotkey.convert_last_word"), last_word_edit)
        hk_layout.addRow(self._tr("cfg.hotkey.toggle"), toggle_edit)
        note = QLabel(self._tr("cfg.hotkey.note"))
        note.setStyleSheet("color: palette(mid);")
        hk_layout.addRow(note)
        tabs.addTab(hk_tab, self._tr("cfg.tab.hotkeys"))

        # ---- Tab: Blacklist ----
        bl_tab = QWidget()
        bl_layout = QVBoxLayout(bl_tab)
        bl_explain = QLabel(self._tr("cfg.bl.explain"))
        bl_explain.setWordWrap(True)
        bl_explain.setStyleSheet("color: palette(mid);")
        bl_layout.addWidget(bl_explain)
        bl_group = QGroupBox(self._tr("cfg.bl.processes"))
        bl_group_layout = QVBoxLayout(bl_group)
        proc_list = QListWidget()
        proc_list.addItems(self._config.get("blacklist", {}).get("processes", []))
        proc_list.setToolTip(self._tr("cfg.bl.hint"))
        bl_group_layout.addWidget(proc_list)
        proc_edit = QLineEdit()
        proc_edit.setPlaceholderText(self._tr("cfg.bl.placeholder"))
        proc_buttons = QHBoxLayout()
        proc_add = QPushButton(self._tr("cfg.bl.add"))
        proc_remove = QPushButton(self._tr("cfg.bl.remove"))
        proc_buttons.addWidget(proc_add)
        proc_buttons.addWidget(proc_remove)
        bl_group_layout.addWidget(proc_edit)
        bl_group_layout.addLayout(proc_buttons)
        bl_layout.addWidget(bl_group)

        def _proc_add() -> None:
            text = proc_edit.text().strip()
            if text:
                proc_list.addItem(text)
                proc_edit.clear()

        def _proc_remove() -> None:
            for item in proc_list.selectedItems():
                proc_list.takeItem(proc_list.row(item))

        proc_add.clicked.connect(_proc_add)
        proc_remove.clicked.connect(_proc_remove)
        tabs.addTab(bl_tab, self._tr("cfg.tab.blacklist"))

        # ---- Tab: Behavior ----
        beh_tab = QWidget()
        beh_layout = QFormLayout(beh_tab)

        fallback_cb = QCheckBox()
        fallback_cb.setChecked(behavior.get("fallback_to_word_on_no_selection", True))
        beh_layout.addRow(self._tr("cfg.beh.fallback"), fallback_cb)

        restore_cb = QCheckBox()
        restore_cb.setChecked(behavior.get("restore_clipboard", True))
        beh_layout.addRow(self._tr("cfg.beh.restore"), restore_cb)

        delay_spin = QSpinBox()
        delay_spin.setRange(10, 500)
        delay_spin.setSuffix(" ms")
        delay_spin.setValue(behavior.get("action_delay_ms", 50))
        beh_layout.addRow(self._tr("cfg.beh.delay"), delay_spin)

        term_paste_combo = QComboBox()
        term_paste_combo.addItems(["ctrl+shift+v", "shift+insert"])
        cur_combo = behavior.get("terminal_paste_combo", "ctrl+shift+v")
        if term_paste_combo.findText(cur_combo) < 0:
            term_paste_combo.addItem(cur_combo)
        term_paste_combo.setCurrentText(cur_combo)
        beh_layout.addRow(self._tr("cfg.beh.terminal_paste"), term_paste_combo)

        tabs.addTab(beh_tab, self._tr("cfg.tab.behavior"))

        # ---- Buttons ----
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(self._tr("cfg.ok"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(
            self._tr("cfg.cancel")
        )

        def _on_accept() -> None:
            new_lang = lang_combo.currentData() or "en"
            new_style = "mono" if mono_cb.isChecked() else "color"

            updated = dict(self._config)
            updated.setdefault("ui", {}).update(
                {"language": new_lang, "tray_icon_style": new_style}
            )
            updated.setdefault("hotkeys", {}).update({
                "convert": convert_edit.text().strip(),
                "convert_terminal": terminal_edit.text().strip(),
                "convert_last_word": last_word_edit.text().strip(),
                "toggle": toggle_edit.text().strip(),
            })
            updated.setdefault("blacklist", {})["processes"] = [
                proc_list.item(i).text() for i in range(proc_list.count())
            ]
            updated.setdefault("behavior", {}).update({
                "fallback_to_word_on_no_selection": fallback_cb.isChecked(),
                "restore_clipboard": restore_cb.isChecked(),
                "action_delay_ms": delay_spin.value(),
                "terminal_paste_combo": term_paste_combo.currentText().strip(),
            })

            sgk_set_autostart(autostart_cb.isChecked())
            self._on_save(updated)
            if self._on_ui_changed is not None:
                try:
                    self._on_ui_changed(new_lang, new_style)
                except Exception:
                    pass
            dialog.accept()

        buttons.accepted.connect(_on_accept)
        buttons.rejected.connect(dialog.reject)

        main_layout = QVBoxLayout(dialog)
        main_layout.addWidget(tabs)
        main_layout.addWidget(buttons)

        dialog.exec()
