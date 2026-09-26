"""Marking a class or factory as a service the container should register.

The class or factory becomes a definition in step 8 (marked definitions),
with an optional
``lifetime`` and ``qualifier``. A plain application service is
``@as_service`` on the class; a factory is ``@as_service`` on the function.
"""

from __future__ import annotations

from collections.abc import Hashable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, TypeVar, cast, overload

from xtr_dependency_injection.builder.definition import Lifetime

from ._marker import own_marker, set_marker

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ["ServiceMarker", "as_service", "service_of"]

T = TypeVar("T")

_SERVICE: Final = "__xtr_service__"


@dataclass(frozen=True, slots=True)
class ServiceMarker:
    """What ``@as_service`` records: the lifetime and qualifier of the service."""

    lifetime: Lifetime = "singleton"
    qualifier: Hashable | None = None


@overload
def as_service(target: T, /) -> T: ...
@overload
def as_service(
    *, lifetime: Lifetime = "singleton", qualifier: Hashable | None = None
) -> Callable[[T], T]: ...
def as_service(
    target: T | None = None,
    /,
    *,
    lifetime: Lifetime = "singleton",
    qualifier: Hashable | None = None,
) -> T | Callable[[T], T]:
    """Register the decorated class or factory as a service.

    Can be used bare (``@as_service``) or called (``@as_service(lifetime=..., qualifier=...)``).

    Args:
        target: The class or factory to mark as a service (when used bare).
        lifetime: How long the container keeps what it builds; defaults to
            ``"singleton"``.
        qualifier: An optional qualifier — a second value in the service
            key ``(type, qualifier)``.
    """

    def mark(obj: T) -> T:
        return set_marker(obj, _SERVICE, ServiceMarker(lifetime=lifetime, qualifier=qualifier))

    return mark(target) if target is not None else mark


def service_of(obj: object) -> ServiceMarker | None:
    """Return what ``@as_service`` recorded on ``obj``, or ``None``."""
    return cast("ServiceMarker | None", own_marker(obj, _SERVICE))
