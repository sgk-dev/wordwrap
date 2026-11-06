"""Unit tests for SgkConfig."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sgk_wordwrap.utils.config import SgkConfig


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    return tmp_path / "config.json"


@pytest.fixture
def config(config_path: Path) -> SgkConfig:
    return SgkConfig(config_path=config_path)


class TestDefaults:
    def test_default_hotkey(self, config: SgkConfig) -> None:
        data = config.sgk_load()
        assert data["hotkeys"]["convert"] == "ctrl+f1"

    def test_default_blacklist_has_keepassxc(self, config: SgkConfig) -> None:
        data = config.sgk_load()
        assert "keepassxc" in data["blacklist"]["processes"]

    def test_default_layouts_section(self, config: SgkConfig) -> None:
        data = config.sgk_load()
        assert data["layouts"] == {"custom_maps_dir": None}

    def test_default_restore_clipboard(self, config: SgkConfig) -> None:
        data = config.sgk_load()
        assert data["behavior"]["restore_clipboard"] is True

    def test_default_behavior_fallback_true(self, config: SgkConfig) -> None:
        data = config.sgk_load()
        assert data["behavior"]["fallback_to_word_on_no_selection"] is True

    def test_default_terminal_and_toggle_hotkeys(self, config: SgkConfig) -> None:
        data = config.sgk_load()
        assert data["hotkeys"]["convert_terminal"] == "ctrl+shift+f1"
        assert data["hotkeys"]["toggle"] == "ctrl+pause"

    def test_default_enabled_on_start(self, config: SgkConfig) -> None:
        data = config.sgk_load()
        assert data["behavior"]["enabled_on_start"] is True

    def test_default_ui_section(self, config: SgkConfig) -> None:
        data = config.sgk_load()
        assert data["ui"]["language"] == "en"
        assert data["ui"]["tray_icon_style"] == "color"

    def test_default_last_word_hotkey(self, config: SgkConfig) -> None:
        data = config.sgk_load()
        assert data["hotkeys"]["convert_last_word"] == "ctrl+f2"

    def test_default_terminal_paste_combo(self, config: SgkConfig) -> None:
        data = config.sgk_load()
        assert data["behavior"]["terminal_paste_combo"] == "ctrl+shift+v"


class TestLoadSave:
    def test_creates_file_on_first_load(
        self, config: SgkConfig, config_path: Path
    ) -> None:
        config.sgk_load()
        assert config_path.exists()

    def test_roundtrip(self, config: SgkConfig, config_path: Path) -> None:
        data = config.sgk_load()
        data["hotkeys"]["convert"] = "ctrl+alt+x"
        config.sgk_save(data)

        config2 = SgkConfig(config_path=config_path)
        loaded = config2.sgk_load()
        assert loaded["hotkeys"]["convert"] == "ctrl+alt+x"

    def test_corrupt_json_falls_back_to_defaults(
        self, config_path: Path
    ) -> None:
        config_path.write_text("{invalid json!!!", encoding="utf-8")
        cfg = SgkConfig(config_path=config_path)
        data = cfg.sgk_load()
        assert data["hotkeys"]["convert"] == "ctrl+f1"


class TestGetSet:
    def test_nested_get(self, config: SgkConfig) -> None:
        config.sgk_load()
        val = config.sgk_get("behavior", "action_delay_ms")
        assert isinstance(val, int)

    def test_get_missing_returns_default(self, config: SgkConfig) -> None:
        config.sgk_load()
        val = config.sgk_get("nonexistent", "key", default="fallback")
        assert val == "fallback"


class TestMergeDefaults:
    def test_missing_keys_filled_from_defaults(
        self, config_path: Path
    ) -> None:
        # Write a partial config missing 'behavior'
        partial = {"version": "1.0", "hotkeys": {"convert": "ctrl+alt+y"}}
        config_path.write_text(json.dumps(partial), encoding="utf-8")

        cfg = SgkConfig(config_path=config_path)
        data = cfg.sgk_load()
        # Custom value preserved
        assert data["hotkeys"]["convert"] == "ctrl+alt+y"
        # Missing section filled from defaults
        assert "fallback_to_word_on_no_selection" in data["behavior"]


class TestMalformedConfig:
    def _load(self, config_path: Path, content: str) -> dict:
        config_path.write_text(content, encoding="utf-8")
        return SgkConfig(config_path=config_path).sgk_load()

    def test_top_level_list_falls_back_to_defaults(self, config_path: Path) -> None:
        data = self._load(config_path, "[1, 2]")
        assert data["hotkeys"]["convert"] == "ctrl+f1"

    def test_corrupt_file_not_overwritten(self, config_path: Path) -> None:
        self._load(config_path, "[]")
        assert config_path.read_text(encoding="utf-8") == "[]"

    def test_null_section_replaced_by_default(self, config_path: Path) -> None:
        data = self._load(config_path, '{"behavior": null}')
        assert data["behavior"]["copy_settle_ms"] == 300

    def test_string_hotkeys_section_ignored(self, config_path: Path) -> None:
        data = self._load(config_path, '{"hotkeys": "ctrl+f1"}')
        assert data["hotkeys"]["toggle"] == "ctrl+pause"

    def test_wrong_type_timing_value_ignored(self, config_path: Path) -> None:
        data = self._load(config_path, '{"behavior": {"copy_settle_ms": "400"}}')
        assert data["behavior"]["copy_settle_ms"] == 300

    def test_bool_for_int_ignored(self, config_path: Path) -> None:
        data = self._load(config_path, '{"behavior": {"max_text_length": true}}')
        assert data["behavior"]["max_text_length"] == 10000

    def test_non_string_hotkey_ignored(self, config_path: Path) -> None:
        data = self._load(config_path, '{"hotkeys": {"convert": 5}}')
        assert data["hotkeys"]["convert"] == "ctrl+f1"

    def test_custom_maps_dir_string_accepted(self, config_path: Path) -> None:
        data = self._load(config_path, '{"layouts": {"custom_maps_dir": "~/maps"}}')
        assert data["layouts"]["custom_maps_dir"] == "~/maps"

    def test_legacy_keys_preserved_on_load(self, config_path: Path) -> None:
        legacy = {
            "version": "1.0",
            "layouts": {"active": ["en", "ru"], "custom_maps_dir": None},
            "behavior": {"word_boundary_chars": " .,", "clipboard_settle_ms": 400},
            "logging": {"level": "DEBUG"},
        }
        data = self._load(config_path, json.dumps(legacy))
        assert data["layouts"]["active"] == ["en", "ru"]
        assert data["behavior"]["word_boundary_chars"] == " .,"
        assert data["behavior"]["clipboard_settle_ms"] == 400
        assert data["logging"]["level"] == "DEBUG"

    def test_save_is_atomic_and_leaves_no_temp_files(self, config: SgkConfig,
                                                      config_path: Path) -> None:
        data = config.sgk_load()
        data["hotkeys"]["convert"] = "ctrl+f9"
        config.sgk_save(data)
        assert json.loads(config_path.read_text(encoding="utf-8"))["hotkeys"]["convert"] == "ctrl+f9"
        assert [p.name for p in config_path.parent.iterdir()] == ["config.json"]

    def test_save_keeps_unicode_readable(self, config: SgkConfig, config_path: Path) -> None:
        data = config.sgk_load()
        data["blacklist"]["window_titles_regex"] = [".*Пароль.*"]
        config.sgk_save(data)
        assert "Пароль" in config_path.read_text(encoding="utf-8")
