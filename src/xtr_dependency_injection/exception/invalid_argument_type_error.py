"""An API of this package was given something of the wrong kind."""

from __future__ import annotations

from .dependency_injection_error import DependencyInjectionError

__all__ = ["InvalidArgumentTypeError"]


class InvalidArgumentTypeError(DependencyInjectionError, TypeError):
    """Something this package was given is not of a kind it accepts.

    Also a :class:`TypeError`, so a caller can catch either this package's
    errors as a whole or the built-in.

    Attributes:
        reason: What was expected, and what was given.
    """

    reason: str

    def __init__(self, reason: str) -> None:
        """Record what was expected, and what was given."""
        self.reason = reason
        super().__init__(reason)
