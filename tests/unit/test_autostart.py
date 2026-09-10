"""Unit tests for the XDG autostart helper."""

from __future__ import annotations

from pathlib import Path

import pytest

from sgk_wordwrap.utils import autostart


@pytest.fixture
def autostart_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    target = tmp_path / "autostart" / "wordwrap.desktop"
    monkeypatch.setattr(autostart, "SGK_AUTOSTART_PATH", target)
    return target


def test_disabled_by_default(autostart_path: Path) -> None:
    assert autostart.sgk_is_autostart_enabled() is False


def test_enable_creates_valid_desktop_entry(autostart_path: Path) -> None:
    state = autostart.sgk_set_autostart(True, exec_cmd="/usr/bin/sgk-wordwrap")
    assert state is True
    assert autostart.sgk_is_autostart_enabled() is True
    content = autostart_path.read_text(encoding="utf-8")
    assert "[Desktop Entry]" in content
    assert "Exec=/usr/bin/sgk-wordwrap" in content
    assert "Name=WordWrap" in content


def test_disable_removes_entry(autostart_path: Path) -> None:
    autostart.sgk_set_autostart(True)
    assert autostart.sgk_is_autostart_enabled() is True
    state = autostart.sgk_set_autostart(False)
    assert state is False
    assert autostart_path.exists() is False


def test_disable_is_idempotent(autostart_path: Path) -> None:
    assert autostart.sgk_set_autostart(False) is False


def test_default_exec_cmd_is_a_string() -> None:
    assert isinstance(autostart.sgk_default_exec_cmd(), str)
    assert autostart.sgk_default_exec_cmd()
