"""Settings dialog for sgk-wordwrap.

Provides a tabbed PyQt6 QDialog for editing:
  - Hotkeys
  - Blacklist (processes, window classes, title patterns)
  - Behavior options
  - Logging settings
"""

from __future__ import annotations

from typing import Any, Callable

from sgk_wordwrap.utils.logger import sgk_get_logger

_logger = sgk_get_logger(__name__)


class SgkConfigDialog:
    """Settings window. Call sgk_show() to open it."""

    def __init__(
        self,
        config_data: dict[str, Any],
        on_save: Callable[[dict[str, Any]], None],
    ) -> None:
        self._config = config_data
        self._on_save = on_save
        self._dialog = None

    def sgk_show(self) -> None:
        """Create and show the settings dialog (blocking modal)."""
        try:
            self._sgk_build_and_exec()
        except ImportError:
            _logger.warning("sgk_dialog_pyqt6_missing")
        except Exception as exc:
            _logger.error("sgk_dialog_error", extra={"error": str(exc)})

    def _sgk_build_and_exec(self) -> None:
        from PyQt6.QtWidgets import (
            QDialog, QDialogButtonBox, QFormLayout, QGroupBox,
            QHBoxLayout, QLabel, QLineEdit, QListWidget, QPushButton,
            QTabWidget, QVBoxLayout, QWidget, QSpinBox, QCheckBox,
        )
        from PyQt6.QtCore import Qt

        dialog = QDialog()
        dialog.setWindowTitle("sgk-wordwrap Settings")
        dialog.setMinimumWidth(460)

        tabs = QTabWidget()

        # ---- Tab: Hotkeys ----
        hotkeys_tab = QWidget()
        hotkeys_layout = QFormLayout(hotkeys_tab)
        hotkey_edit = QLineEdit(
            self._config.get("hotkeys", {}).get("convert", "ctrl+shift+z")
        )
        hotkeys_layout.addRow("Convert hotkey:", hotkey_edit)
        tabs.addTab(hotkeys_tab, "Hotkeys")

        # ---- Tab: Blacklist ----
        bl_tab = QWidget()
        bl_layout = QVBoxLayout(bl_tab)

        bl_processes_group = QGroupBox("Blocked processes")
        bl_proc_layout = QVBoxLayout(bl_processes_group)
        proc_list = QListWidget()
        proc_list.addItems(
            self._config.get("blacklist", {}).get("processes", [])
        )
        proc_list.setToolTip("One process name per line (e.g., keepassxc)")
        bl_proc_layout.addWidget(proc_list)
        proc_edit = QLineEdit()
        proc_edit.setPlaceholderText("Add process name...")
        proc_buttons = QHBoxLayout()
        proc_add = QPushButton("Add")
        proc_remove = QPushButton("Remove")
        proc_buttons.addWidget(proc_add)
        proc_buttons.addWidget(proc_remove)
        bl_proc_layout.addWidget(proc_edit)
        bl_proc_layout.addLayout(proc_buttons)
        bl_layout.addWidget(bl_processes_group)

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

        tabs.addTab(bl_tab, "Blacklist")

        # ---- Tab: Behavior ----
        beh_tab = QWidget()
        beh_layout = QFormLayout(beh_tab)
        behavior = self._config.get("behavior", {})

        fallback_cb = QCheckBox()
        fallback_cb.setChecked(behavior.get("fallback_to_word_on_no_selection", True))
        beh_layout.addRow("Word fallback (no selection):", fallback_cb)

        restore_cb = QCheckBox()
        restore_cb.setChecked(behavior.get("restore_clipboard", True))
        beh_layout.addRow("Restore clipboard after paste:", restore_cb)

        delay_spin = QSpinBox()
        delay_spin.setRange(10, 500)
        delay_spin.setSuffix(" ms")
        delay_spin.setValue(behavior.get("action_delay_ms", 50))
        beh_layout.addRow("Action delay:", delay_spin)

        tabs.addTab(beh_tab, "Behavior")

        # ---- Buttons ----
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )

        def _on_accept() -> None:
            updated = dict(self._config)
            updated.setdefault("hotkeys", {})["convert"] = hotkey_edit.text().strip()
            updated.setdefault("blacklist", {})["processes"] = [
                proc_list.item(i).text() for i in range(proc_list.count())
            ]
            updated.setdefault("behavior", {}).update({
                "fallback_to_word_on_no_selection": fallback_cb.isChecked(),
                "restore_clipboard": restore_cb.isChecked(),
                "action_delay_ms": delay_spin.value(),
            })
            self._on_save(updated)
            dialog.accept()

        buttons.accepted.connect(_on_accept)
        buttons.rejected.connect(dialog.reject)

        main_layout = QVBoxLayout(dialog)
        main_layout.addWidget(tabs)
        main_layout.addWidget(buttons)

        dialog.exec()
