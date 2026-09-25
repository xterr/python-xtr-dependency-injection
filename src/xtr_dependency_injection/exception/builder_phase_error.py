"""A builder operation was used in a phase that does not own it."""

from __future__ import annotations

from .dependency_injection_error import DependencyInjectionError

__all__ = ["BuilderPhaseError"]


class BuilderPhaseError(DependencyInjectionError):
    """An operation was called outside the phases it belongs to.

    ``scan`` and ``autoconfigure`` only mean something while bundles load:
    after that, scanning and autoconfiguration have already run.
    """

    operation: str
    phase: str

    def __init__(self, operation: str, phase: str) -> None:
        """Record the operation and the phase it was attempted in."""
        self.operation = operation
        self.phase = phase
        super().__init__(f"{operation}() cannot be called during the {phase} phase")
