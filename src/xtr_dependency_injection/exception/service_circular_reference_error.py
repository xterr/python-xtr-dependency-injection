"""Aliases that point at each other and never reach a definition."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._naming import key_name
from .dependency_injection_error import DependencyInjectionError

if TYPE_CHECKING:
    from collections.abc import Hashable

__all__ = ["ServiceCircularReferenceError"]


class ServiceCircularReferenceError(DependencyInjectionError):
    """An alias chain loops back on itself.

    Attributes:
        key: Where the loop was entered.
        path: Every key of the loop, ending with the first one again.
    """

    key: tuple[type, Hashable | None]
    path: tuple[tuple[type, Hashable | None], ...]

    def __init__(
        self,
        key: tuple[type, Hashable | None],
        path: tuple[tuple[type, Hashable | None], ...],
    ) -> None:
        """Record the key and the path of the loop."""
        self.key = key
        self.path = path
        joined = " -> ".join(key_name(step) for step in path)
        super().__init__(f"circular reference detected for {key_name(key)}, path: {joined}")
