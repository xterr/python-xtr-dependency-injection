"""Running application code as the kernel boots and shuts down.

Hooks are injected: an ``Injected[...]`` parameter is filled from the
container. They may be sync or async.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, TypeVar, cast, overload

from ._marker import own_marker, set_marker

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ["LifecycleMarker", "on_boot", "on_boot_of", "on_shutdown", "on_shutdown_of"]

F = TypeVar("F", bound="Callable[..., object]")

_ON_BOOT: Final = "__xtr_on_boot__"
_ON_SHUTDOWN: Final = "__xtr_on_shutdown__"


@dataclass(frozen=True, slots=True)
class LifecycleMarker:
    """What ``@on_boot`` or ``@on_shutdown`` records: its order among the hooks."""

    priority: int = 0


@overload
def on_boot(fn: F, /) -> F: ...
@overload
def on_boot(*, priority: int = 0) -> Callable[[F], F]: ...
def on_boot(fn: F | None = None, /, *, priority: int = 0) -> F | Callable[[F], F]:
    """Run the decorated function once the bundles have booted; highest ``priority`` first."""
    return _marking(_ON_BOOT, fn, priority)


@overload
def on_shutdown(fn: F, /) -> F: ...
@overload
def on_shutdown(*, priority: int = 0) -> Callable[[F], F]: ...
def on_shutdown(fn: F | None = None, /, *, priority: int = 0) -> F | Callable[[F], F]:
    """Run the decorated function first as the kernel shuts down; highest ``priority`` first."""
    return _marking(_ON_SHUTDOWN, fn, priority)


def on_boot_of(obj: object) -> LifecycleMarker | None:
    """Return what ``@on_boot`` recorded on ``obj``, or ``None``."""
    return cast("LifecycleMarker | None", own_marker(obj, _ON_BOOT))


def on_shutdown_of(obj: object) -> LifecycleMarker | None:
    """Return what ``@on_shutdown`` recorded on ``obj``, or ``None``."""
    return cast("LifecycleMarker | None", own_marker(obj, _ON_SHUTDOWN))


def _marking(name: str, fn: F | None, priority: int) -> F | Callable[[F], F]:
    def decorate(target: F) -> F:
        return set_marker(target, name, LifecycleMarker(priority))

    return decorate(fn) if fn is not None else decorate
