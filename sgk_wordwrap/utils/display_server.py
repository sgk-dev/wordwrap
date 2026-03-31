"""Detect the active display server (X11 or Wayland)."""

from __future__ import annotations

import os
from typing import Literal

DisplayServer = Literal["x11", "wayland"]


def sgk_detect_display_server() -> DisplayServer:
    """Return 'wayland' or 'x11' based on environment variables.

    Priority:
    1. XDG_SESSION_TYPE (most reliable, set by login manager)
    2. WAYLAND_DISPLAY presence
    3. DISPLAY presence
    4. Default to 'x11'
    """
    session_type = os.environ.get("XDG_SESSION_TYPE", "").lower()
    if session_type == "wayland":
        return "wayland"
    if session_type == "x11":
        return "x11"

    # Fallback: check display variables
    if os.environ.get("WAYLAND_DISPLAY"):
        return "wayland"
    if os.environ.get("DISPLAY"):
        return "x11"

    return "x11"


def sgk_is_wayland() -> bool:
    return sgk_detect_display_server() == "wayland"


def sgk_is_x11() -> bool:
    return sgk_detect_display_server() == "x11"
