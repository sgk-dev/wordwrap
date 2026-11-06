from __future__ import annotations

import sgk_wordwrap.layouts.detector as det
from sgk_wordwrap.layouts.detector import SgkFieldDetector


def test_invalid_title_regex_skipped() -> None:
    d = SgkFieldDetector(title_patterns=["[", ".*[Pp]assword.*"])
    assert d.sgk_is_sensitive_context(window_title="Enter password") is True
    assert d.sgk_is_sensitive_context(window_title="Notes") is False


def test_builtin_sensitive_process_matched_case_insensitive() -> None:
    assert SgkFieldDetector().sgk_is_sensitive_context(process_name="KeePassXC") is True


def test_extra_process_from_config_matched() -> None:
    d = SgkFieldDetector(extra_processes=["myvault"])
    assert d.sgk_is_sensitive_context(process_name="MyVault") is True
    assert d.sgk_is_sensitive_context(process_name="firefox") is False


def test_wayland_window_info_all_none(monkeypatch) -> None:
    monkeypatch.setattr(det, "sgk_detect_display_server", lambda: "wayland")
    assert SgkFieldDetector().sgk_get_active_window_info() == (None, None, None)
