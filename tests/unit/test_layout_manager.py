"""Unit tests for gsettings parsing helpers in SgkLayoutManager."""

from __future__ import annotations

from sgk_wordwrap.core.layout_manager import (
    _sgk_normalize,
    _sgk_parse_gsettings_current,
    _sgk_parse_gsettings_sources,
)


class TestParseCurrent:
    def test_plain_uint32_prefix(self) -> None:
        assert _sgk_parse_gsettings_current("uint32 1") == 1

    def test_plain_integer(self) -> None:
        assert _sgk_parse_gsettings_current("2") == 2

    def test_zero(self) -> None:
        assert _sgk_parse_gsettings_current("uint32 0") == 0

    def test_garbage_returns_zero(self) -> None:
        assert _sgk_parse_gsettings_current("nonsense") == 0

    def test_whitespace(self) -> None:
        assert _sgk_parse_gsettings_current("  uint32 3  ") == 3


class TestParseSources:
    def test_two_sources(self) -> None:
        raw = "[('xkb', 'us'), ('xkb', 'ru')]"
        assert _sgk_parse_gsettings_sources(raw) == ["us", "ru"]

    def test_variant_with_options(self) -> None:
        raw = "[('xkb', 'ru+phonetic'), ('xkb', 'us')]"
        assert _sgk_parse_gsettings_sources(raw) == ["ru", "us"]

    def test_ignores_ibus(self) -> None:
        raw = "[('xkb', 'us'), ('ibus', 'anthy')]"
        assert _sgk_parse_gsettings_sources(raw) == ["us"]

    def test_garbage_returns_empty(self) -> None:
        assert _sgk_parse_gsettings_sources("not a list") == []


class TestNormalize:
    def test_us_to_en(self) -> None:
        assert _sgk_normalize("us") == "en"

    def test_ua_to_uk(self) -> None:
        assert _sgk_normalize("ua") == "uk"

    def test_passthrough(self) -> None:
        assert _sgk_normalize("ru") == "ru"
