"""A unit of work's scoped services did not finish their teardown in time."""

from __future__ import annotations

from .dependency_injection_error import DependencyInjectionError

__all__ = ["ScopeTeardownTimeoutError"]


class ScopeTeardownTimeoutError(DependencyInjectionError):
    """Closing a unit's scoped services took longer than it is given.

    Each teardown is the code after ``yield`` in a scoped factory; one that
    never returns — a connection that hangs on close — would otherwise hold
    the unit, and whatever waits for it, forever.
    """

    timeout: float

    def __init__(self, timeout: float) -> None:
        """Record how long the teardown was given."""
        self.timeout = timeout
        super().__init__(
            f"the unit's scoped services did not finish closing within {timeout} seconds"
        )
