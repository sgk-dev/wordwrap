"""Integration tests for SgkClipboard.

These touch the real system clipboard and are timing-sensitive (wl-copy forks to
hold the selection), so they are opt-in. Enable with:

    SGK_INTEGRATION=1 pytest tests/integration/ -v

Needs a working X11 (xclip) or Wayland (wl-clipboard) clipboard in the session.
"""

from __future__ import annotations

import os
import shutil

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("SGK_INTEGRATION") != "1"
    or not (shutil.which("xclip") or shutil.which("wl-copy")),
    reason="Set SGK_INTEGRATION=1 (and have xclip/wl-clipboard) to run",
)


@pytest.fixture
def clipboard():
    from sgk_wordwrap.input.clipboard import SgkClipboard
    return SgkClipboard(action_delay_ms=20)


@pytest.mark.asyncio
async def test_set_and_get_roundtrip(clipboard) -> None:
    text = "sgk_wordwrap_test_string_42"
    await clipboard.sgk_set(text, confirm=True)
    result = await clipboard.sgk_get()
    assert result == text


@pytest.mark.asyncio
async def test_unicode_roundtrip(clipboard) -> None:
    text = "Привет мир! Hello World! Слава Україні!"
    await clipboard.sgk_set(text, confirm=True)
    result = await clipboard.sgk_get()
    assert result == text


@pytest.mark.asyncio
async def test_save_and_restore(clipboard) -> None:
    saved = await clipboard.sgk_get()
    assert await clipboard.sgk_set("temporary content", confirm=True)
    assert await clipboard.sgk_get() == "temporary content"
    if saved is None:
        await clipboard.sgk_clear()
        return
    assert await clipboard.sgk_set(saved, confirm=True)
    assert await clipboard.sgk_get() == saved
