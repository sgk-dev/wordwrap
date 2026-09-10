"""Configuration management for sgk-wordwrap.

Config file: ~/.config/sgk-wordwrap/config.json
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sgk_wordwrap.utils.logger import sgk_get_logger

_logger = sgk_get_logger(__name__)

_SGK_DEFAULT_CONFIG: dict[str, Any] = {
    "version": "1.0",
    "hotkeys": {
        "convert": "ctrl+f1",
        "convert_terminal": "ctrl+shift+f1",
        "toggle": "ctrl+pause",
    },
    "layouts": {
        "active": ["en", "ru"],
        "cycle": True,
        "custom_maps_dir": None,
    },
    "blacklist": {
        "processes": [
            "keepassxc",
            "pinentry",
            "pinentry-qt",
            "pinentry-gtk",
            "1password",
            "gnupg",
            "pkexec",
            "gksu",
            "gksudo",
        ],
        "window_classes": [
            "Pinentry",
            "Pinentry-qt",
            "Pinentry-gtk",
        ],
        "window_titles_regex": [
            ".*[Pp]assword.*",
            ".*Пароль.*",
            ".*[Pp]in [Ee]ntry.*",
        ],
    },
    "behavior": {
        "enabled_on_start": True,
        "fallback_to_word_on_no_selection": True,
        "word_boundary_chars": " \t\n.,;:!?()[]{}\"'",
        "restore_clipboard": True,
        "clipboard_read_timeout_ms": 200,
        "action_delay_ms": 50,
        "clipboard_settle_ms": 80,
        "paste_settle_ms": 80,
        "hotkey_settle_ms": 150,
        "max_text_length": 10000,
    },
    "logging": {
        "level": "INFO",
        "file": "~/.local/share/sgk-wordwrap/wordwrap.log",
        "format": "json",
        "max_bytes": 1_048_576,
        "backup_count": 3,
    },
}


class SgkConfig:
    CONFIG_PATH = Path.home() / ".config" / "sgk-wordwrap" / "config.json"

    def __init__(self, config_path: Path | None = None) -> None:
        self._path = config_path or self.CONFIG_PATH
        self._data: dict[str, Any] = {}

    def sgk_load(self) -> dict[str, Any]:
        """Load config from disk. Falls back to defaults on any error."""
        if not self._path.exists():
            _logger.info("sgk_config_not_found", extra={"path": str(self._path)})
            self._data = self.sgk_get_default()
            self.sgk_save(self._data)
            return self._data

        try:
            with self._path.open("r", encoding="utf-8") as f:
                loaded = json.load(f)
            self._data = self._sgk_merge_defaults(loaded)
            _logger.info("sgk_config_loaded", extra={"path": str(self._path)})
        except (json.JSONDecodeError, OSError) as exc:
            _logger.warning(
                "sgk_config_load_failed",
                extra={"path": str(self._path), "error": str(exc)},
            )
            self._data = self.sgk_get_default()

        return self._data

    def sgk_save(self, data: dict[str, Any] | None = None) -> None:
        """Save config to disk."""
        if data is not None:
            self._data = data
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
            _logger.debug("sgk_config_saved", extra={"path": str(self._path)})
        except OSError as exc:
            _logger.error(
                "sgk_config_save_failed",
                extra={"path": str(self._path), "error": str(exc)},
            )

    def sgk_get(self, *keys: str, default: Any = None) -> Any:
        """Nested key access: sgk_get('behavior', 'action_delay_ms')."""
        node = self._data
        for key in keys:
            if not isinstance(node, dict):
                return default
            node = node.get(key, default)
        return node

    def sgk_set(self, *keys: str, value: Any) -> None:
        """Set nested key and persist."""
        node = self._data
        for key in keys[:-1]:
            node = node.setdefault(key, {})
        node[keys[-1]] = value
        self.sgk_save()

    @staticmethod
    def sgk_get_default() -> dict[str, Any]:
        import copy
        return copy.deepcopy(_SGK_DEFAULT_CONFIG)

    def _sgk_merge_defaults(self, loaded: dict[str, Any]) -> dict[str, Any]:
        """Deep-merge loaded config with defaults (defaults fill missing keys)."""
        import copy
        result = copy.deepcopy(_SGK_DEFAULT_CONFIG)
        _sgk_deep_merge(result, loaded)
        return result

    @property
    def data(self) -> dict[str, Any]:
        return self._data


def _sgk_deep_merge(base: dict[str, Any], override: dict[str, Any]) -> None:
    """Merge override into base in-place (recursive)."""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _sgk_deep_merge(base[key], value)
        else:
            base[key] = value
