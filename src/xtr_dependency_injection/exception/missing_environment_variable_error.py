"""An environment variable a config reads is not set."""

from __future__ import annotations

from .dependency_injection_error import DependencyInjectionError

__all__ = ["MissingEnvironmentVariableError"]


class MissingEnvironmentVariableError(DependencyInjectionError):
    """An environment variable a service needs is not set, and has no default."""

    name: str

    def __init__(self, name: str) -> None:
        """Record the variable's name."""
        self.name = name
        super().__init__(f"environment variable {name} is not set and has no default")
