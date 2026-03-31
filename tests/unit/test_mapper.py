"""Unit tests for SgkLayoutMapper."""

from __future__ import annotations

import json
import pytest
from pathlib import Path
from sgk_wordwrap.layouts.mapper import SgkLayoutMapper


@pytest.fixture
def mapper(tmp_path: Path) -> SgkLayoutMapper:
    m = SgkLayoutMapper()
    m.sgk_load_maps()
    return m


class TestEnRuForward:
    def test_lowercase_letters(self, mapper: SgkLayoutMapper) -> None:
        assert mapper.sgk_convert("ghbdtn", "en", "ru") == "привет"

    def test_uppercase_letters(self, mapper: SgkLayoutMapper) -> None:
        assert mapper.sgk_convert("GHBDTN", "en", "ru") == "ПРИВЕТ"

    def test_mixed_case(self, mapper: SgkLayoutMapper) -> None:
        assert mapper.sgk_convert("Ghbdtn", "en", "ru") == "Привет"

    def test_full_alphabet_lowercase(self, mapper: SgkLayoutMapper) -> None:
        en = "qwertyuiopasdfghjklzxcvbnm"
        ru = mapper.sgk_convert(en, "en", "ru")
        # All characters should be Cyrillic
        assert all(
            "\u0400" <= ch <= "\u04FF" or ch in " \t\n" for ch in ru
        ), f"Unexpected char in: {ru}"

    def test_special_chars(self, mapper: SgkLayoutMapper) -> None:
        assert mapper.sgk_convert("[", "en", "ru") == "х"
        assert mapper.sgk_convert("]", "en", "ru") == "ъ"
        assert mapper.sgk_convert(";", "en", "ru") == "ж"
        assert mapper.sgk_convert("'", "en", "ru") == "э"
        assert mapper.sgk_convert(",", "en", "ru") == "б"
        assert mapper.sgk_convert(".", "en", "ru") == "ю"

    def test_backtick_yo(self, mapper: SgkLayoutMapper) -> None:
        assert mapper.sgk_convert("`", "en", "ru") == "ё"
        assert mapper.sgk_convert("~", "en", "ru") == "Ё"

    def test_digits_passthrough(self, mapper: SgkLayoutMapper) -> None:
        # Digits are the same in both layouts
        assert mapper.sgk_convert("1234567890", "en", "ru") == "1234567890"

    def test_unknown_chars_passthrough(self, mapper: SgkLayoutMapper) -> None:
        assert mapper.sgk_convert("€@#", "en", "ru") == "€@#"

    def test_empty_string(self, mapper: SgkLayoutMapper) -> None:
        assert mapper.sgk_convert("", "en", "ru") == ""


class TestRuEnReverse:
    def test_reverse_conversion(self, mapper: SgkLayoutMapper) -> None:
        original = "ghbdtn"
        ru = mapper.sgk_convert(original, "en", "ru")
        back = mapper.sgk_convert(ru, "ru", "en")
        assert back == original

    def test_reverse_full_alphabet(self, mapper: SgkLayoutMapper) -> None:
        en = "abcdefghijklmnopqrstuvwxyz"
        ru = mapper.sgk_convert(en, "en", "ru")
        back = mapper.sgk_convert(ru, "ru", "en")
        assert back == en


class TestEnUkForward:
    def test_ukrainian_specific_chars(self, mapper: SgkLayoutMapper) -> None:
        # 's' in EN → 'і' in UK (differs from RU 'ы')
        assert mapper.sgk_convert("s", "en", "uk") == "і"

    def test_uk_yi(self, mapper: SgkLayoutMapper) -> None:
        assert mapper.sgk_convert("]", "en", "uk") == "ї"


class TestNoMapFallback:
    def test_unknown_layout_pair_returns_original(
        self, mapper: SgkLayoutMapper
    ) -> None:
        result = mapper.sgk_convert("hello", "en", "de")
        assert result == "hello"


class TestHasMap:
    def test_has_en_ru(self, mapper: SgkLayoutMapper) -> None:
        assert mapper.sgk_has_map("en", "ru")
        assert mapper.sgk_has_map("ru", "en")

    def test_has_en_uk(self, mapper: SgkLayoutMapper) -> None:
        assert mapper.sgk_has_map("en", "uk")

    def test_missing_pair(self, mapper: SgkLayoutMapper) -> None:
        assert not mapper.sgk_has_map("de", "fr")


class TestCustomMap:
    def test_custom_map_loaded(self, tmp_path: Path) -> None:
        custom_dir = tmp_path / "layouts"
        custom_dir.mkdir()
        custom_map = {
            "name": "en-de-test",
            "from_layout": "en",
            "to_layout": "de",
            "description": "Test",
            "map": {"a": "ä", "o": "ö", "u": "ü"},
        }
        (custom_dir / "en_de.json").write_text(
            json.dumps(custom_map), encoding="utf-8"
        )
        m = SgkLayoutMapper(custom_maps_dir=custom_dir)
        m.sgk_load_maps()
        assert m.sgk_has_map("en", "de")
        assert m.sgk_convert("aou", "en", "de") == "äöü"
