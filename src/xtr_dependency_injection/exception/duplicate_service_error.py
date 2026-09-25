"""Two definitions claim one service key."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._naming import key_name
from .dependency_injection_error import DependencyInjectionError

if TYPE_CHECKING:
    from collections.abc import Hashable

    from xtr_dependency_injection.builder.definition import Origin

__all__ = ["DuplicateServiceError"]


class DuplicateServiceError(DependencyInjectionError):
    """Two definitions claim one key, and neither is allowed to override the other.

    The application overrides a bundle silently; two bundles, or two
    application definitions, never do — unless a bundle calls
    ``builder.replace`` on purpose.
    """

    key: tuple[type, Hashable | None]
    first: Origin
    second: Origin

    def __init__(self, key: tuple[type, Hashable | None], first: Origin, second: Origin) -> None:
        """Record the key and the origins of both definitions."""
        self.key = key
        self.first = first
        self.second = second
        super().__init__(f"{key_name(key)} is defined by both {first} and {second}")
