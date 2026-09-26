"""A container is asked for a parameter that is not defined."""

from __future__ import annotations

from .dependency_injection_error import DependencyInjectionError

__all__ = ["ParameterNotFoundError"]


class ParameterNotFoundError(DependencyInjectionError, LookupError):
    """No parameter is set for this dotted name.

    Raised by :class:`ContainerInterface.get_parameter` when
    :meth:`has_parameter` is ``False`` for the same name, so callers can catch
    a ``LookupError`` without coupling to this package.
    """

    name: str

    def __init__(self, name: str) -> None:
        """Record the parameter name that is not defined."""
        self.name = name
        super().__init__(f"parameter {name!r} is not defined")
