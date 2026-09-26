"""A definition, or an alias, that cannot be compiled as it stands."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._naming import key_name
from .dependency_injection_error import DependencyInjectionError

if TYPE_CHECKING:
    from collections.abc import Hashable

__all__ = ["InvalidDefinitionError"]


class InvalidDefinitionError(DependencyInjectionError):
    """A compiler pass found a definition or alias inconsistent with itself.

    Raised before the engine sees the container: a provider that does not
    match its kind or key, an unknown lifetime, a ``kernel.reset`` tag naming
    no method, an alias whose target does not implement it.
    """

    key: tuple[type, Hashable | None]
    reason: str

    def __init__(self, key: tuple[type, Hashable | None], reason: str) -> None:
        """Record the key and why its definition is invalid."""
        self.key = key
        self.reason = reason
        super().__init__(f"invalid definition of {key_name(key)}: {reason}")
