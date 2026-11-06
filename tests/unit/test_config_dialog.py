from __future__ import annotations

import pytest

from sgk_wordwrap.gui.config_dialog import sgk_find_hotkey_problem, sgk_hotkey_clashes


@pytest.fixture(autouse=True)
def _need_evdev() -> None:
    pytest.importorskip("evdev")


def test_valid_hotkeys_pass() -> None:
    assert sgk_find_hotkey_problem({
        "convert": "ctrl+f1", "convert_terminal": "ctrl+shift+f1",
        "convert_last_word": "ctrl+f2", "toggle": "ctrl+pause",
    }) is None


def test_validate_rejects_duplicate_hotkeys() -> None:
    assert sgk_find_hotkey_problem({"convert": "ctrl+f1", "convert_last_word": "Ctrl+F1"}) == (
        "duplicate", "convert_last_word", "convert"
    )


def test_duplicate_ignores_modifier_order_and_style() -> None:
    problem = sgk_find_hotkey_problem({"a": "ctrl+shift+f1", "b": "<Shift><Primary>F1"})
    assert problem == ("duplicate", "b", "a")


def test_validate_rejects_invalid_hotkey_names_field() -> None:
    assert sgk_find_hotkey_problem({"convert": "ctrl+f1", "toggle": "ctrl+alt"}) == (
        "invalid", "toggle", None
    )


def test_switch_clash_detected() -> None:
    assert sgk_hotkey_clashes("Super+Space", "super+space") is True
    assert sgk_hotkey_clashes("ctrl+f1", "super+space") is False


def test_dialog_strings_resolve_in_both_languages() -> None:
    from sgk_wordwrap.gui.i18n import sgk_tr

    for lang in ("en", "ru"):
        text = sgk_tr("cfg.hotkey.duplicate", lang).format(field="A", value="ctrl+f1", other="B")
        assert "ctrl+f1" in text
        assert "ctrl+f1" in sgk_tr("cfg.hotkey.switch_clash", lang).format(
            field="A", value="ctrl+f1"
        )
