"""Clipboard and key simulation abstraction layer.

X11:     xclip + xdotool
Wayland: wl-clipboard (wl-paste/wl-copy) + a uinput virtual keyboard

Converted text is delivered as clipboard swap + synthetic paste: `wtype` is
unsupported by Mutter and keycode-level typing is layout-dependent. Only text
is read from the clipboard; an empty or non-text clipboard reads as None.
"""

from __future__ import annotations

import asyncio
import shutil
import time
from typing import Any, NamedTuple

from sgk_wordwrap.input.uinput_backend import SgkUinputInjector
from sgk_wordwrap.utils.display_server import sgk_detect_display_server
from sgk_wordwrap.utils.logger import sgk_get_logger

_logger = sgk_get_logger(__name__)

_CLIPBOARD_TIMEOUT = 0.5
_RETRY_DELAY = 0.05
_RETRIES = 2
_VISIBLE_TIMEOUT_S = 0.8
_VISIBLE_POLL_S = 0.02
_BLOB_TIMEOUT_S = 2.0
_BLOB_MAX_BYTES = 20 * 1024 * 1024
_TEXT_TYPE_PREFIXES = ("text/",)
_SKIP_TYPES = frozenset({
    "UTF8_STRING", "STRING", "TEXT", "COMPOUND_TEXT", "TARGETS", "MULTIPLE",
    "TIMESTAMP", "SAVE_TARGETS", "x-kde-passwordManagerHint",
})


class SgkClipboardBlob(NamedTuple):
    mime: str
    data: bytes


class SgkClipboard:
    """Clipboard read/write and text input for X11 and Wayland."""

    def __init__(
        self,
        action_delay_ms: int = 50,
        clipboard_settle_ms: int = 0,
        paste_settle_ms: int = 100,
        uinput: SgkUinputInjector | None = None,
    ) -> None:
        self._display = sgk_detect_display_server()
        self._delay = action_delay_ms / 1000.0
        self._clipboard_settle = clipboard_settle_ms / 1000.0
        self._paste_settle = paste_settle_ms / 1000.0

        self._uinput: SgkUinputInjector | None = uinput
        if self._uinput is None and self._display == "wayland":
            self._uinput = SgkUinputInjector()

    # ------------------------------------------------------------------
    # Clipboard (CLIPBOARD / PRIMARY selections)
    # ------------------------------------------------------------------

    def _sgk_get_cmd(self, primary: bool) -> list[str]:
        if self._display == "wayland":
            cmd = ["wl-paste", "--type", "text", "--no-newline"]
            return cmd + ["--primary"] if primary else cmd
        sel = "primary" if primary else "clipboard"
        return ["xclip", "-selection", sel, "-o"]

    def _sgk_set_cmd(self, primary: bool) -> list[str]:
        if self._display == "wayland":
            return ["wl-copy", "--primary"] if primary else ["wl-copy"]
        sel = "primary" if primary else "clipboard"
        return ["xclip", "-selection", sel, "-i"]

    async def sgk_get(self) -> str | None:
        """Read CLIPBOARD as text. None when empty, non-text or on failure."""
        for attempt in range(_RETRIES):
            try:
                return await self._sgk_run_get(self._sgk_get_cmd(primary=False))
            except Exception as exc:
                if attempt < _RETRIES - 1:
                    await asyncio.sleep(_RETRY_DELAY)
                else:
                    _logger.warning("sgk_clipboard_get_failed", extra={"error": str(exc)})
        return None

    async def sgk_get_primary(self) -> str | None:
        """Read PRIMARY selection (the last mouse selection) as text."""
        try:
            return await self._sgk_run_get(self._sgk_get_cmd(primary=True))
        except Exception as exc:
            _logger.debug("sgk_primary_get_failed", extra={"error": str(exc)})
        return None

    async def sgk_set(self, text: str, confirm: bool = False) -> bool:
        """Write text to CLIPBOARD. Returns True on success."""
        for attempt in range(_RETRIES):
            try:
                await self._sgk_run_set(self._sgk_set_cmd(primary=False), text)
                return await self._sgk_wait_visible(text) if confirm else True
            except Exception as exc:
                if attempt < _RETRIES - 1:
                    await asyncio.sleep(_RETRY_DELAY)
                else:
                    _logger.warning("sgk_clipboard_set_failed", extra={"error": str(exc)})
        return False

    async def sgk_snapshot_non_text(self) -> SgkClipboardBlob | None:
        if self._display != "wayland":
            return None
        try:
            raw = await self._sgk_run_get(["wl-paste", "--list-types"])
        except Exception as exc:
            _logger.debug("sgk_clipboard_types_failed", extra={"error": repr(exc)})
            return None
        if not raw:
            return None
        mime = next(
            (
                t for t in (line.strip() for line in raw.splitlines())
                if t and t not in _SKIP_TYPES and not t.startswith(_TEXT_TYPE_PREFIXES)
            ),
            None,
        )
        if mime is None:
            return None
        try:
            data = await self._sgk_run_get_bytes(["wl-paste", "--type", mime], _BLOB_TIMEOUT_S)
        except Exception as exc:
            _logger.warning("sgk_clipboard_snapshot_failed", extra={"error": repr(exc)})
            return None
        if data is None:
            return None
        if len(data) > _BLOB_MAX_BYTES:
            _logger.warning("sgk_clipboard_snapshot_too_big", extra={"size": len(data)})
            return None
        _logger.debug("sgk_clipboard_snapshot", extra={"mime": mime, "size": len(data)})
        return SgkClipboardBlob(mime, data)

    async def sgk_set_blob(self, blob: SgkClipboardBlob) -> bool:
        try:
            await self._sgk_run_set_bytes(
                ["wl-copy", "--type", blob.mime], blob.data, _BLOB_TIMEOUT_S
            )
            return True
        except Exception as exc:
            _logger.warning("sgk_clipboard_blob_restore_failed", extra={"error": repr(exc)})
            return False

    async def sgk_clear(self) -> None:
        await self._sgk_clear(primary=False)

    async def sgk_clear_primary(self) -> None:
        await self._sgk_clear(primary=True)

    async def _sgk_clear(self, primary: bool) -> None:
        try:
            if self._display == "wayland":
                await self._sgk_run_set(self._sgk_set_cmd(primary) + ["--clear"], "")
            else:
                await self._sgk_run_set(self._sgk_set_cmd(primary), "")
        except Exception as exc:
            _logger.debug(
                "sgk_clipboard_clear_failed",
                extra={"primary": primary, "error": str(exc)},
            )

    # ------------------------------------------------------------------
    # Text input (replaces selected text in focused app)
    # ------------------------------------------------------------------

    async def sgk_paste_text(self, text: str, combo: str = "ctrl+v") -> bool:
        """Put `text` on the CLIPBOARD and paste it with `combo`.

        Wayland: wl-copy + the combo through uinput (Ctrl+V, or the terminal
        combo such as Ctrl+Shift+V). X11: xdotool type. The caller saves and
        restores the user's clipboard around this call. Returns True if the
        paste was issued.
        """
        await asyncio.sleep(self._delay)
        try:
            if self._display != "wayland":
                return await self._sgk_type_x11(text)
            if not (self._uinput and self._uinput.sgk_is_available()):
                _logger.error(
                    "sgk_uinput_unavailable",
                    extra={"hint": "uinput virtual keyboard not usable - cannot paste"},
                )
                return False
            await self._sgk_run_set(self._sgk_set_cmd(primary=False), text)
            if not await self._sgk_wait_visible(text):
                _logger.warning("sgk_paste_clipboard_not_ready", extra={"len": len(text)})
                return False
            if self._clipboard_settle:
                await asyncio.sleep(self._clipboard_settle)
            self._uinput.sgk_send_combo(combo)
            await asyncio.sleep(self._paste_settle)
            _logger.debug("sgk_paste_sent", extra={"combo": combo, "len": len(text)})
            return True
        except Exception as exc:
            _logger.warning("sgk_paste_text_failed", extra={"error": str(exc)})
            return False

    async def _sgk_type_x11(self, text: str) -> bool:
        proc = await asyncio.create_subprocess_exec(
            "xdotool", "type", "--clearmodifiers", "--", text,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.wait(), timeout=_CLIPBOARD_TIMEOUT + len(text) * 0.002)
        return proc.returncode == 0

    async def sgk_backspace(self, count: int) -> None:
        """Press Backspace `count` times (erase text, e.g. in a terminal)."""
        if count <= 0:
            return
        await asyncio.sleep(self._delay)
        try:
            if self._display == "wayland" and self._uinput and self._uinput.sgk_is_available():
                self._uinput.sgk_backspace(count)
            else:
                proc = await asyncio.create_subprocess_exec(
                    "xdotool", "key", "--clearmodifiers",
                    *(["BackSpace"] * count),
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await asyncio.wait_for(proc.wait(), timeout=_CLIPBOARD_TIMEOUT + count * 0.01)
        except Exception as exc:
            _logger.warning("sgk_backspace_failed", extra={"error": str(exc)})

    # ------------------------------------------------------------------
    # Key simulation
    # ------------------------------------------------------------------

    async def sgk_send_key(self, combo: str) -> None:
        """Simulate a key combo (Ctrl+Insert, Ctrl+Shift+Left, Ctrl+A ...)."""
        await asyncio.sleep(self._delay)
        try:
            if self._display == "wayland":
                await self._sgk_send_key_wayland(combo)
            else:
                await self._sgk_send_key_x11(combo)
        except Exception as exc:
            _logger.warning("sgk_send_key_failed", extra={"combo": combo, "error": str(exc)})
        await asyncio.sleep(self._delay)

    async def sgk_send_key_repeat(self, combo: str, count: int) -> None:
        if count <= 1 or self._display != "wayland" or not (
            self._uinput and self._uinput.sgk_is_available()
        ):
            for _ in range(max(1, count)):
                await self.sgk_send_key(combo)
            return
        await asyncio.sleep(self._delay)
        try:
            self._uinput.sgk_send_combo_repeat(combo, count)
        except Exception as exc:
            _logger.warning("sgk_send_key_failed", extra={"combo": combo, "error": str(exc)})
        await asyncio.sleep(self._delay)

    async def _sgk_send_key_x11(self, combo: str) -> None:
        proc = await asyncio.create_subprocess_exec(
            "xdotool", "key", "--clearmodifiers", combo,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.wait(), timeout=_CLIPBOARD_TIMEOUT)

    async def _sgk_send_key_wayland(self, combo: str) -> None:
        if self._uinput and self._uinput.sgk_is_available():
            self._uinput.sgk_send_combo(combo)
            return

        if shutil.which("wtype"):
            wtype_args = self._sgk_combo_to_wtype(combo)
            if wtype_args:
                proc = await asyncio.create_subprocess_exec(
                    "wtype", *wtype_args,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await asyncio.wait_for(proc.wait(), timeout=_CLIPBOARD_TIMEOUT)
                if proc.returncode == 0:
                    return

        if shutil.which("ydotool"):
            ydotool_key = self._sgk_combo_to_ydotool(combo)
            proc = await asyncio.create_subprocess_exec(
                "ydotool", "key", ydotool_key,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.wait(), timeout=_CLIPBOARD_TIMEOUT)

    def _sgk_combo_to_wtype(self, combo: str) -> list[str] | None:
        """Convert 'ctrl+shift+Left' -> ['-M', 'ctrl', '-M', 'shift', '-P', 'left']."""
        _map = {
            "ctrl": "ctrl", "shift": "shift",
            "alt": "alt", "super": "logo", "logo": "logo",
        }
        parts = combo.split("+")
        args = []
        for part in parts[:-1]:
            mod = _map.get(part.lower())
            if not mod:
                return None
            args.extend(["-M", mod])

        args.extend(["-P", parts[-1].lower()])

        for part in reversed(parts[:-1]):
            mod = _map.get(part.lower())
            if mod:
                args.extend(["-m", mod])

        return args

    def _sgk_combo_to_ydotool(self, combo: str) -> str:
        _map = {
            "ctrl": "KEY_LEFTCTRL", "shift": "KEY_LEFTSHIFT",
            "alt": "KEY_LEFTALT", "super": "KEY_LEFTMETA",
        }
        parts = combo.split("+")
        result = []
        for part in parts:
            lower = part.lower()
            if lower in _map:
                result.append(_map[lower])
            else:
                result.append(f"KEY_{part.upper()}")
        return "+".join(result)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _sgk_wait_visible(self, text: str) -> bool:
        if self._display != "wayland":
            return True
        want = text.rstrip("\n")
        t0 = time.monotonic()
        while True:
            try:
                current = await self._sgk_run_get(self._sgk_get_cmd(primary=False))
            except Exception:
                current = None
            waited = time.monotonic() - t0
            if current is not None and current.rstrip("\n") == want:
                _logger.debug("sgk_clipboard_visible", extra={"wait_ms": round(waited * 1000)})
                return True
            if waited >= _VISIBLE_TIMEOUT_S:
                return False
            await asyncio.sleep(_VISIBLE_POLL_S)

    async def _sgk_run_get(self, cmd: list[str]) -> str | None:
        data = await self._sgk_run_get_bytes(cmd, _CLIPBOARD_TIMEOUT)
        if data is None:
            return None
        return data.decode("utf-8", errors="replace")

    async def _sgk_run_get_bytes(self, cmd: list[str], timeout: float) -> bytes | None:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout = await self._sgk_communicate(proc, None, timeout)
        if proc.returncode != 0:
            return None
        return stdout

    async def _sgk_run_set(self, cmd: list[str], text: str) -> None:
        await self._sgk_run_set_bytes(cmd, text.encode("utf-8"), _CLIPBOARD_TIMEOUT)

    async def _sgk_run_set_bytes(self, cmd: list[str], data: bytes, timeout: float) -> None:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await self._sgk_communicate(proc, data, timeout)
        if proc.returncode:
            _logger.warning(
                "sgk_clipboard_cmd_failed", extra={"cmd": cmd[0], "rc": proc.returncode}
            )

    @staticmethod
    async def _sgk_communicate(proc, data: bytes | None, timeout: float) -> bytes:
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(data), timeout=timeout)
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            await proc.wait()
            raise
        return stdout

    @staticmethod
    def sgk_is_text_safe(content: Any, max_length: int = 10000) -> bool:
        if not isinstance(content, str):
            return False
        stripped = content.strip()
        if not stripped:
            return False
        if len(stripped) > max_length:
            return False
        return True
