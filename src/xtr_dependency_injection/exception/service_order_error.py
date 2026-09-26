"""A ``before``/``after`` constraint is unsatisfiable, contradictory or cyclic."""

from __future__ import annotations

from .dependency_injection_error import DependencyInjectionError

__all__ = ["ServiceOrderError"]


class ServiceOrderError(DependencyInjectionError):
    """The ``before``/``after`` constraints on tagged services cannot be satisfied.

    Raised by :func:`sort_with_priorities` when a constraint contradicts an
    explicit priority, when the bounds derived from unprioritised items are
    unsatisfiable, or when the constraints form a cycle. ``reason`` is the
    sorter's message, verbatim.
    """

    reason: str

    def __init__(self, reason: str) -> None:
        """Record the sorter's message describing what is wrong."""
        self.reason = reason
        super().__init__(reason)
