"""An operation targets a service that has no definition."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Hashable

from ._naming import key_name
from .dependency_injection_error import DependencyInjectionError

__all__ = ["UnknownServiceError"]


class UnknownServiceError(DependencyInjectionError):
    """``replace``, ``remove``, ``decorate`` or ``resettable`` target a key nothing defines."""

    key: tuple[type, Hashable | None]
    operation: str

    def __init__(self, key: tuple[type, Hashable | None], operation: str) -> None:
        """Record the key and the operation that needed it."""
        self.key = key
        self.operation = operation
        super().__init__(f"cannot {operation} {key_name(key)}: no service is defined for it")
