"""Single-instance guard.

Two running daemons means two evdev listeners, so every hotkey fires twice and
the conversions race each other. This takes an exclusive ``flock`` on a lock
file for the lifetime of the process; a second launch fails to take it and
should exit.
"""

from __future__ import annotations

import fcntl
import os
from pathlib import Path

from sgk_wordwrap.utils.logger import sgk_get_logger

_logger = sgk_get_logger(__name__)

_LOCK_PATH = (
    Path(os.environ.get("XDG_RUNTIME_DIR", str(Path.home() / ".local" / "share")))
    / "sgk-wordwrap.lock"
)

# Kept alive for the whole process so the lock is held until exit.
_lock_fd: int | None = None


def sgk_acquire_single_instance() -> bool:
    """Try to become the only running instance. True on success."""
    global _lock_fd
    try:
        _LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(_LOCK_PATH), os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        _logger.warning("sgk_already_running", extra={"lock": str(_LOCK_PATH)})
        return False
    os.ftruncate(fd, 0)
    os.write(fd, f"{os.getpid()}\n".encode())
    _lock_fd = fd
    return True
