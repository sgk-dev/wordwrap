"""Unit tests for the single-instance lock."""

from __future__ import annotations

import fcntl
import os
from pathlib import Path

import pytest

from sgk_wordwrap.utils import single_instance as si


@pytest.fixture(autouse=True)
def _isolated_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(si, "_LOCK_PATH", tmp_path / "wordwrap.lock")
    monkeypatch.setattr(si, "_lock_fd", None)
    yield
    if si._lock_fd is not None:
        os.close(si._lock_fd)
        si._lock_fd = None


def test_first_acquire_succeeds_and_writes_pid() -> None:
    assert si.sgk_acquire_single_instance() is True
    assert si._LOCK_PATH.read_text().strip() == str(os.getpid())


def test_lock_is_actually_held() -> None:
    assert si.sgk_acquire_single_instance() is True
    other = os.open(str(si._LOCK_PATH), os.O_RDWR)
    try:
        with pytest.raises(BlockingIOError):
            fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        os.close(other)
