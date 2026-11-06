"""Unit tests for the GUI translation table."""

from __future__ import annotations

from sgk_wordwrap.gui.i18n import (
    _STRINGS,
    SGK_LANGUAGES,
    sgk_normalize_lang,
    sgk_tr,
)


def test_default_language_is_english() -> None:
    assert sgk_tr("tray.settings") == "Settings..."


def test_russian_translation() -> None:
    assert sgk_tr("tray.settings", "ru") == "Настройки..."


def test_unknown_key_returns_key() -> None:
    assert sgk_tr("no.such.key", "ru") == "no.such.key"


def test_unknown_language_falls_back_to_english() -> None:
    assert sgk_tr("tray.quit", "de") == "Quit"


def test_normalize_language() -> None:
    assert sgk_normalize_lang("RU") == "ru"
    assert sgk_normalize_lang(None) == "en"
    assert sgk_normalize_lang("klingon") == "en"


def test_every_string_has_all_languages() -> None:
    for key, entry in _STRINGS.items():
        for lang in SGK_LANGUAGES:
            assert entry.get(lang), f"{key} missing {lang}"


def test_no_em_dash_in_strings() -> None:
    for key, entry in _STRINGS.items():
        for lang, value in entry.items():
            assert "—" not in value, f"{key}/{lang} contains an em dash"


def test_no_en_dash_in_strings() -> None:
    for key, entry in _STRINGS.items():
        for lang, value in entry.items():
            assert "\u2013" not in value, f"{key}/{lang} contains an en dash"


def test_placeholders_match_across_languages() -> None:
    import string

    def _fields(value: str) -> set[str]:
        return {f for _, f, _, _ in string.Formatter().parse(value) if f}

    for key, entry in _STRINGS.items():
        assert _fields(entry["en"]) == _fields(entry["ru"]), key


def test_every_key_used_in_gui_exists() -> None:
    import pathlib
    import re

    import sgk_wordwrap.gui as gui

    used: set[str] = set()
    for path in pathlib.Path(gui.__file__).parent.glob("*.py"):
        used |= set(re.findall(r"_tr\(\s*\"([a-z_.]+)\"", path.read_text(encoding="utf-8")))
        used |= set(re.findall(r"sgk_tr\(\s*\"([a-z_.]+)\"", path.read_text(encoding="utf-8")))
        used |= set(re.findall(r"\(\"(cfg\.hotkey\.[a-z_]+)\",", path.read_text(encoding="utf-8")))
    for mode in ("line", "word", "backspace"):
        used.add(f"cfg.beh.erase.{mode}")
    missing = sorted(k for k in used if k not in _STRINGS)
    assert not missing, missing
