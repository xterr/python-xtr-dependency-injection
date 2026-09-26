"""The engine failed to build an already-registered service."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._naming import key_name
from .dependency_injection_error import DependencyInjectionError

if TYPE_CHECKING:
    from collections.abc import Hashable

__all__ = ["ServiceResolutionError"]


class ServiceResolutionError(DependencyInjectionError):
    """The engine failed to build an already-registered service.

    Raised by :class:`ContainerInterface.get` when the service is registered
    (:meth:`has` is true) but the engine could not build it. :attr:`reason`
    is the engine's own message, repeated in this error's message; the
    original engine error is available via ``__cause__``. ``advice`` names how
    this package resolves the service when the engine failed for a reason a
    caller can act on (a scoped or transient service requested without a
    scope).
    """

    key: tuple[type, Hashable | None]
    reason: str

    def __init__(
        self,
        key: tuple[type, Hashable | None],
        reason: str,
        /,
        *,
        advice: str | None = None,
    ) -> None:
        """Record the key whose resolution failed and the engine's message."""
        self.key = key
        self.reason = reason
        message = f"failed to resolve {key_name(key)}: {reason}"
        if advice is not None:
            message = f"{message}\n{advice}"
        super().__init__(message)
