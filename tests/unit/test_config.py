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

    def test_default_layouts(self, config: SgkConfig) -> None:
        data = config.sgk_load()
        assert "en" in data["layouts"]["active"]
        assert "ru" in data["layouts"]["active"]

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
