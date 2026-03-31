"""Keyboard layout detection and switching.

Abstracts over:
  - xkb-switch (X11, primary)
  - setxkbmap (X11, fallback)
  - gsettings (GNOME Wayland)
  - D-Bus / qdbus (KDE Wayland)
"""

from __future__ import annotations

import shutil
import subprocess
from typing import Protocol

from sgk_wordwrap.utils.display_server import sgk_detect_display_server
from sgk_wordwrap.utils.logger import sgk_get_logger

_logger = sgk_get_logger(__name__)


class _SgkLayoutBackend(Protocol):
    def get_current(self) -> str: ...
    def get_all(self) -> list[str]: ...
    def switch_next(self) -> None: ...
    def switch_to(self, layout: str) -> None: ...


class _SgkXkbSwitch:
    """xkb-switch based backend (X11)."""

    def get_current(self) -> str:
        out = subprocess.check_output(["xkb-switch"], text=True, timeout=1.0).strip()
        # xkb-switch may return 'ru(phonetic)' — normalize to base name
        return out.split("(")[0].strip()

    def get_all(self) -> list[str]:
        out = subprocess.check_output(
            ["xkb-switch", "-l"], text=True, timeout=1.0
        ).strip()
        return [line.split("(")[0].strip() for line in out.splitlines() if line.strip()]

    def switch_next(self) -> None:
        subprocess.run(["xkb-switch", "-n"], timeout=1.0, check=True)

    def switch_to(self, layout: str) -> None:
        subprocess.run(["xkb-switch", "-s", layout], timeout=1.0, check=True)


class _SgkSetxkbmap:
    """setxkbmap fallback for X11 (no query capability, limited)."""

    def __init__(self) -> None:
        self._layouts: list[str] = []
        self._current_idx: int = 0

    def get_current(self) -> str:
        try:
            out = subprocess.check_output(
                ["setxkbmap", "-query"], text=True, timeout=1.0
            )
            for line in out.splitlines():
                if line.startswith("layout:"):
                    layouts_str = line.split(":", 1)[1].strip()
                    all_layouts = [l.strip() for l in layouts_str.split(",")]
                    if all_layouts:
                        return all_layouts[self._current_idx % len(all_layouts)]
        except Exception:
            pass
        return "en"

    def get_all(self) -> list[str]:
        try:
            out = subprocess.check_output(
                ["setxkbmap", "-query"], text=True, timeout=1.0
            )
            for line in out.splitlines():
                if line.startswith("layout:"):
                    layouts_str = line.split(":", 1)[1].strip()
                    return [l.strip() for l in layouts_str.split(",")]
        except Exception:
            pass
        return ["en"]

    def switch_next(self) -> None:
        all_layouts = self.get_all()
        self._current_idx = (self._current_idx + 1) % len(all_layouts)
        self.switch_to(all_layouts[self._current_idx])

    def switch_to(self, layout: str) -> None:
        all_layouts = self.get_all()
        subprocess.run(
            ["setxkbmap", ",".join(all_layouts)],
            timeout=1.0,
        )
        # Use xdotool to activate specific group index
        if layout in all_layouts:
            idx = all_layouts.index(layout)
            subprocess.run(
                ["xdotool", "key", f"XF86Switch_VT_{idx + 1}"],
                timeout=1.0,
                stderr=subprocess.DEVNULL,
            )


class _SgkGsettings:
    """GNOME Wayland: gsettings org.gnome.desktop.input-sources."""

    def get_current(self) -> str:
        try:
            idx_str = subprocess.check_output(
                ["gsettings", "get", "org.gnome.desktop.input-sources", "current"],
                text=True, timeout=1.0,
            ).strip()
            idx = int(idx_str) if idx_str.isdigit() else 0
            all_layouts = self.get_all()
            if idx < len(all_layouts):
                return all_layouts[idx]
        except Exception:
            pass
        return "en"

    def get_all(self) -> list[str]:
        try:
            raw = subprocess.check_output(
                ["gsettings", "get", "org.gnome.desktop.input-sources", "sources"],
                text=True, timeout=1.0,
            ).strip()
            # Format: [('xkb', 'en'), ('xkb', 'ru')]
            import ast
            sources = ast.literal_eval(raw)
            return [src[1].split("+")[0] for src in sources if src[0] == "xkb"]
        except Exception:
            pass
        return ["en"]

    def switch_next(self) -> None:
        all_layouts = self.get_all()
        current = self.get_current()
        idx = all_layouts.index(current) if current in all_layouts else 0
        next_idx = (idx + 1) % len(all_layouts)
        subprocess.run(
            ["gsettings", "set", "org.gnome.desktop.input-sources",
             "current", str(next_idx)],
            timeout=1.0,
        )

    def switch_to(self, layout: str) -> None:
        all_layouts = self.get_all()
        if layout in all_layouts:
            idx = all_layouts.index(layout)
            subprocess.run(
                ["gsettings", "set", "org.gnome.desktop.input-sources",
                 "current", str(idx)],
                timeout=1.0,
            )


class SgkLayoutManager:
    """Unified layout manager — auto-selects the best backend."""

    def __init__(self) -> None:
        self._backend: _SgkLayoutBackend = self._sgk_pick_backend()

    def _sgk_pick_backend(self) -> _SgkLayoutBackend:
        display = sgk_detect_display_server()

        if display == "x11":
            if shutil.which("xkb-switch"):
                _logger.info("sgk_layout_backend", extra={"backend": "xkb-switch"})
                return _SgkXkbSwitch()
            if shutil.which("setxkbmap"):
                _logger.warning(
                    "sgk_layout_backend_fallback",
                    extra={"backend": "setxkbmap", "hint": "Install xkb-switch for better support"},
                )
                return _SgkSetxkbmap()
        else:
            # Wayland: try GNOME gsettings
            if shutil.which("gsettings"):
                try:
                    subprocess.check_output(
                        ["gsettings", "get", "org.gnome.desktop.input-sources", "sources"],
                        timeout=1.0, stderr=subprocess.DEVNULL,
                    )
                    _logger.info("sgk_layout_backend", extra={"backend": "gsettings"})
                    return _SgkGsettings()
                except Exception:
                    pass

        _logger.error(
            "sgk_no_layout_backend",
            extra={"hint": "Install xkb-switch: sudo apt install xkb-switch"},
        )
        return _SgkSetxkbmap()

    def sgk_get_current_layout(self) -> str:
        try:
            return self._backend.get_current()
        except Exception as exc:
            _logger.warning("sgk_get_layout_failed", extra={"error": str(exc)})
            return "en"

    def sgk_get_active_layouts(self) -> list[str]:
        try:
            return self._backend.get_all()
        except Exception as exc:
            _logger.warning("sgk_get_layouts_failed", extra={"error": str(exc)})
            return ["en", "ru"]

    def sgk_switch_to_next(self) -> str:
        """Switch to next layout and return the new layout name."""
        try:
            self._backend.switch_next()
            new = self.sgk_get_current_layout()
            _logger.debug("sgk_layout_switched", extra={"to": new})
            return new
        except Exception as exc:
            _logger.warning("sgk_switch_layout_failed", extra={"error": str(exc)})
            return "unknown"

    def sgk_switch_to(self, layout: str) -> None:
        try:
            self._backend.switch_to(layout)
        except Exception as exc:
            _logger.warning(
                "sgk_switch_to_failed",
                extra={"layout": layout, "error": str(exc)},
            )

    def sgk_get_next_layout(self) -> str:
        """Return the name of the next layout without switching."""
        layouts = self.sgk_get_active_layouts()
        current = self.sgk_get_current_layout()
        if not layouts:
            return "ru"
        idx = layouts.index(current) if current in layouts else 0
        return layouts[(idx + 1) % len(layouts)]
