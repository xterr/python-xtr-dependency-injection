"""Parameters that reference each other and never reach a value."""

from __future__ import annotations

from .dependency_injection_error import DependencyInjectionError

__all__ = ["ParameterCircularReferenceError"]


class ParameterCircularReferenceError(DependencyInjectionError):
    """A ``%name%`` reference loops back on itself.

    Attributes:
        path: Every parameter of the loop, ending with the first one again.
    """

    path: tuple[str, ...]

    def __init__(self, path: tuple[str, ...]) -> None:
        """Record the path of the loop."""
        self.path = path
        joined = " -> ".join(f"%{name}%" for name in path)
        super().__init__(f"circular reference detected for parameter {path[0]!r}, path: {joined}")
