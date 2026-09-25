"""Bundles depend on each other in a loop."""

from __future__ import annotations

from .dependency_injection_error import DependencyInjectionError

__all__ = ["CircularBundleDependencyError"]


class CircularBundleDependencyError(DependencyInjectionError):
    """Bundles depend on each other, through ``requires`` or ``optional``, in a loop."""

    cycle: tuple[str, ...]

    def __init__(self, cycle: tuple[str, ...]) -> None:
        """Record the loop, its first bundle repeated at the end."""
        self.cycle = cycle
        super().__init__(f"circular bundle dependency: {' -> '.join(cycle)}")
