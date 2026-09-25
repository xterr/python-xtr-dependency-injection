"""The builder was changed after the container was compiled."""

from __future__ import annotations

from .dependency_injection_error import DependencyInjectionError

__all__ = ["BuilderFrozenError"]


class BuilderFrozenError(DependencyInjectionError):
    """A definition was changed after compilation; the container would never see it."""

    operation: str

    def __init__(self, operation: str) -> None:
        """Record the operation attempted."""
        self.operation = operation
        super().__init__(f"{operation}() cannot be called: the container is already compiled")
