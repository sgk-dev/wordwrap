"""Unit tests for gsettings parsing helpers in SgkLayoutManager."""

from __future__ import annotations

import pytest

from sgk_wordwrap.core.layout_manager import (
    _sgk_normalize,
    _sgk_parse_gsettings_current,
    _sgk_parse_gsettings_sources,
    _SgkGsettings,
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

    def test_typed_empty_array(self) -> None:
        assert _sgk_parse_gsettings_sources("@a(ss) []") == []

    def test_typed_array_with_items(self) -> None:
        assert _sgk_parse_gsettings_sources("@a(ss) [('xkb', 'ru')]") == ["ru"]


class TestGsettingsCurrent:
    @pytest.fixture
    def backend(self, monkeypatch: pytest.MonkeyPatch):
        values = {
            "sources": "[('xkb', 'us'), ('xkb', 'ru')]",
            "current": "uint32 1",
            "mru-sources": "[('xkb', 'us'), ('xkb', 'ru')]",
        }
        b = _SgkGsettings()
        monkeypatch.setattr(b, "_get", lambda key: values[key])
        b._values = values  # type: ignore[attr-defined]
        return b

    def test_mru_wins_over_stale_current(self, backend: _SgkGsettings) -> None:
        assert backend.get_current() == "us"

    def test_falls_back_to_current_when_mru_empty(self, backend: _SgkGsettings) -> None:
        backend._values["mru-sources"] = "@a(ss) []"
        assert backend.get_current() == "ru"

    def test_current_out_of_range_defaults_en(self, backend: _SgkGsettings) -> None:
        backend._values["mru-sources"] = "@a(ss) []"
        backend._values["current"] = "uint32 7"
        assert backend.get_current() == "en"


class TestNormalize:
    def test_us_to_en(self) -> None:
        assert _sgk_normalize("us") == "en"

    def test_ua_to_uk(self) -> None:
        assert _sgk_normalize("ua") == "uk"

    def test_passthrough(self) -> None:
        assert _sgk_normalize("ru") == "ru"


class TestParseIbusEngine:
    @pytest.mark.parametrize("raw, want", [
        ("xkb:us::eng\n", "us"),
        ("xkb:ru:phonetic:rus", "ru"),
        ("xkb:ua::ukr", "ua"),
        ("anthy", None),
        ("", None),
        ("xkb::", None),
    ])
    def test_parse(self, raw: str, want) -> None:
        from sgk_wordwrap.core.layout_manager import _sgk_parse_ibus_engine

        assert _sgk_parse_ibus_engine(raw) == want


class _Proc:
    def __init__(self, out: str, rc: int = 0) -> None:
        self.stdout = out
        self.returncode = rc


class TestGsettingsLive:
    @pytest.fixture
    def backend(self, monkeypatch: pytest.MonkeyPatch):
        import sgk_wordwrap.core.layout_manager as lm

        values = {
            "sources": "[('xkb', 'us'), ('xkb', 'ru')]",
            "current": "uint32 1",
            "mru-sources": "[('xkb', 'ru'), ('xkb', 'us')]",
            "per-window": "true\n",
        }
        ibus = {"out": "xkb:us::eng\n", "rc": 0, "raise": False}

        def fake_run(cmd, **kwargs):
            assert cmd == ["ibus", "engine"]
            if ibus["raise"]:
                raise FileNotFoundError("ibus")
            return _Proc(ibus["out"], ibus["rc"])

        b = _SgkGsettings()
        monkeypatch.setattr(b, "_get", lambda key: values[key])
        monkeypatch.setattr(lm.subprocess, "run", fake_run)
        b._values = values  # type: ignore[attr-defined]
        b._ibus = ibus  # type: ignore[attr-defined]
        return b

    def test_per_window_uses_ibus_over_stale_mru(self, backend) -> None:
        assert backend.get_current() == "us"
        assert backend.get_mru_current() == "ru"

    def test_shared_layout_uses_mru(self, backend) -> None:
        backend._values["per-window"] = "false"
        assert backend.get_current() == "ru"

    def test_ibus_missing_falls_back_to_mru(self, backend) -> None:
        backend._ibus["raise"] = True
        assert backend.sgk_get_live() is None
        assert backend.get_current() == "ru"

    def test_ibus_error_exit_is_unreliable(self, backend) -> None:
        backend._ibus["rc"] = 1
        assert backend.sgk_get_live() is None

    def test_non_xkb_engine_is_unreliable(self, backend) -> None:
        backend._ibus["out"] = "anthy\n"
        assert backend.sgk_get_live() is None

    def test_engine_outside_sources_is_unreliable(self, backend) -> None:
        backend._ibus["out"] = "xkb:de::ger\n"
        assert backend.sgk_get_live() is None

    def test_per_window_flag(self, backend) -> None:
        assert backend.sgk_per_window() is True
        backend._values["per-window"] = "false"
        assert backend.sgk_per_window() is False

    def test_switch_to_does_not_write_gsettings(self, backend, monkeypatch) -> None:
        import sgk_wordwrap.core.layout_manager as lm

        def boom(*args, **kwargs):
            raise AssertionError("switch_to must not run a subprocess")

        monkeypatch.setattr(lm.subprocess, "run", boom)
        backend.switch_to("ru")
        backend.switch_next()


class TestManagerLive:
    def _manager(self, backend):
        from sgk_wordwrap.core.layout_manager import SgkLayoutManager

        m = SgkLayoutManager.__new__(SgkLayoutManager)
        m._backend = backend
        return m

    def test_live_layout_is_normalized(self, monkeypatch) -> None:
        b = _SgkGsettings()
        monkeypatch.setattr(b, "sgk_get_live", lambda: "us")
        m = self._manager(b)
        assert m.sgk_get_live_layout() == "en"
        assert m.sgk_uses_shortcut_switch() is True

    def test_mru_layouts_normalized(self, monkeypatch) -> None:
        b = _SgkGsettings()
        monkeypatch.setattr(b, "get_mru", lambda: ["ru", "us"])
        monkeypatch.setattr(b, "get_mru_current", lambda: "ru")
        m = self._manager(b)
        assert m.sgk_get_mru_layouts() == ["ru", "en"]
        assert m.sgk_get_mru_layout() == "ru"

    def test_non_gsettings_backend_has_no_live_reader(self) -> None:
        class _X11:
            def get_current(self):
                return "us"

            def get_all(self):
                return ["us", "ru"]

        m = self._manager(_X11())
        assert m.sgk_get_live_layout() is None
        assert m.sgk_per_window() is False
        assert m.sgk_uses_shortcut_switch() is False
        assert m.sgk_get_mru_layouts() == []
        assert m.sgk_get_mru_layout() == "en"
