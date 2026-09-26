"""The engine refused to compile the container."""

from __future__ import annotations

from .dependency_injection_error import DependencyInjectionError

__all__ = ["ContainerCompilationError"]


class ContainerCompilationError(DependencyInjectionError):
    """The engine refused to compile the container.

    Raised by the compiler when the underlying engine reports the definitions
    do not form a valid container (e.g. an unresolvable constructor
    dependency). The original engine error is available via ``__cause__``;
    any origin notes the compiler attached to it are preserved.
    """

    reason: str

    def __init__(self, reason: str) -> None:
        """Record the engine's message."""
        self.reason = reason
        super().__init__(reason)
