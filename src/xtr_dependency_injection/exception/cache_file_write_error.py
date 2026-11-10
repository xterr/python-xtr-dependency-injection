"""A cache warmer could not write one of its files."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .dependency_injection_error import DependencyInjectionError

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["CacheFileWriteError"]


class CacheFileWriteError(DependencyInjectionError):
    """A cache file could not be written; the filesystem's error is its ``__cause__``.

    Attributes:
        path: The file that was to be written.
    """

    path: Path

    def __init__(self, path: Path) -> None:
        """Record the file that could not be written."""
        self.path = path
        super().__init__(f'failed to write cache file "{path}"')
