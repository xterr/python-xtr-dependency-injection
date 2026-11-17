"""A context variable is registered for new connections with two different values."""

from __future__ import annotations

from .dependency_injection_error import DependencyInjectionError

__all__ = ["DetachedVariableConflictError"]


class DetachedVariableConflictError(DependencyInjectionError):
    """A context variable already registered to start new connections at another value.

    Every kernel in a process shares one registry, so the same variable may
    be registered again — with the same value, which changes nothing. Two
    values would leave a new connection's start depending on which came last.
    """

    name: str

    def __init__(self, name: str, registered: object, value: object) -> None:
        """Record the variable and the two values it was registered with."""
        self.name = name
        super().__init__(
            f"{name!r} already starts new connections at {registered!r}, not {value!r}"
        )
