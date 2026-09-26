"""A service locator was asked for a key it does not hold."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Hashable

from .dependency_injection_error import DependencyInjectionError

__all__ = ["UnknownLocatorKeyError"]


class UnknownLocatorKeyError(DependencyInjectionError, LookupError):
    """A service locator was asked for a key it does not hold."""

    key: Hashable
    known: tuple[Hashable, ...]

    def __init__(self, key: Hashable, known: tuple[Hashable, ...]) -> None:
        """Record the key asked for and those the locator holds."""
        self.key = key
        self.known = known
        held = ", ".join(repr(entry) for entry in known) or "<none>"
        super().__init__(f"unknown locator key {key!r}; known: {held}")
