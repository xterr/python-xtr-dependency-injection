"""One parameter is set twice."""

from __future__ import annotations

from .dependency_injection_error import DependencyInjectionError

__all__ = ["ParameterConflictError"]


class ParameterConflictError(DependencyInjectionError):
    """A parameter leaf is set by two sources; parameters merge, they do not override."""

    path: tuple[str, ...]
    first: str
    second: str

    def __init__(self, path: tuple[str, ...], first: str, second: str) -> None:
        """Record the parameter's path and the two sources setting it."""
        self.path = path
        self.first = first
        self.second = second
        super().__init__(f"parameter {'.'.join(path)!r} is set by both {first} and {second}")
