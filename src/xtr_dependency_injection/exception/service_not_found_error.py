"""A container is asked for a service it does not know."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._naming import key_name
from .dependency_injection_error import DependencyInjectionError

if TYPE_CHECKING:
    from collections.abc import Hashable

__all__ = ["ServiceNotFoundError"]


class ServiceNotFoundError(DependencyInjectionError, LookupError):
    """No service is registered under this ``(type, qualifier)`` key.

    Raised by :class:`ContainerInterface.get` when :meth:`has` is ``False``
    for the same arguments, so callers can catch a ``LookupError`` without
    coupling to this package.
    """

    key: tuple[type, Hashable | None]

    def __init__(self, key: tuple[type, Hashable | None]) -> None:
        """Record the key nothing was registered for."""
        self.key = key
        super().__init__(f"{key_name(key)} is not registered in the container")
