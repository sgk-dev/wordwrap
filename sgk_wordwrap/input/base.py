"""Abstract base class for hotkey listener backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable


class SgkInputBackend(ABC):
    """Backend-agnostic interface for global hotkey interception."""

    @abstractmethod
    def sgk_start(self, on_hotkey: Callable[[], None]) -> None:
        """Start listening. Calls on_hotkey() from a background thread when triggered."""

    @abstractmethod
    def sgk_stop(self) -> None:
        """Stop listening and release all resources."""

    @abstractmethod
    def sgk_is_available(self) -> bool:
        """Return True if this backend can operate in the current environment."""
