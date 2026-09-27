"""An API of this package was given a value it cannot use."""

from __future__ import annotations

from .dependency_injection_error import DependencyInjectionError

__all__ = ["InvalidArgumentError"]


class InvalidArgumentError(DependencyInjectionError, ValueError):
    """A value this package was given cannot be used as it is.

    Also a :class:`ValueError`, so a caller can catch either this package's
    errors as a whole or the built-in.

    Attributes:
        reason: What is wrong with the value.
    """

    reason: str

    def __init__(self, reason: str) -> None:
        """Record what is wrong with the value."""
        self.reason = reason
        super().__init__(reason)
