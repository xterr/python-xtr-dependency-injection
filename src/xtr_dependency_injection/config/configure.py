"""Configuring a bundle from the application: ``@configure``.

Two forms, told apart by their signature::

    @configure  # base: replaces the bundle's default
    def logging() -> LoggingConfig: ...


    @configure  # transform: receives the current value
    def logging_prod(config: LoggingConfig) -> LoggingConfig: ...

The return annotation says which bundle is configured: the one whose config
type it is.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, TypeVar, cast, overload

from xtr_dependency_injection.decorator._marker import own_marker, set_marker

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ["ConfigureMarker", "configure", "configure_of"]

F = TypeVar("F", bound="Callable[..., object]")

_CONFIGURE: Final = "__xtr_configure__"


@dataclass(frozen=True, slots=True)
class ConfigureMarker:
    """What ``@configure`` records: the provider's order among transforms."""

    priority: int = 0


@overload
def configure(fn: F, /) -> F: ...
@overload
def configure(*, priority: int = 0) -> Callable[[F], F]: ...
def configure(fn: F | None = None, /, *, priority: int = 0) -> F | Callable[[F], F]:
    """Provide or transform a bundle's config from the decorated function.

    Transforms run by ``priority``, highest first, then in scan order. Put
    ``@when`` or ``@when_not`` on it to keep it to some environments.
    Its annotations are read at runtime: import their types at runtime, not
    under ``TYPE_CHECKING``.
    """

    def record(target: F) -> F:
        return set_marker(target, _CONFIGURE, ConfigureMarker(priority))

    return record(fn) if fn is not None else record


def configure_of(obj: object) -> ConfigureMarker | None:
    """Return what ``@configure`` recorded on ``obj``, or ``None``."""
    return cast("ConfigureMarker | None", own_marker(obj, _CONFIGURE))
