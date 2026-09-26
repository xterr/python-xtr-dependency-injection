"""Resetting stateful services between units of work — Symfony's ``kernel.reset``.

A long-running worker handles one message after another with the same
singletons. A service that buffers or caches per unit of work declares a
reset method; the worker calls :meth:`ServicesResetter.reset` after each
message, and only services that were actually built are reset.
"""

from __future__ import annotations

import inspect
import weakref
from typing import TYPE_CHECKING, cast, final

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ["ServicesResetter"]


@final
class ServicesResetter:
    """Tracks built resettable services and resets them on demand."""

    __slots__ = ("_tracked",)

    def __init__(self) -> None:
        """Track nothing yet: services are tracked as the container builds them."""
        self._tracked: dict[int, tuple[Callable[[], object | None], str]] = {}

    def track(self, instance: object, method: str) -> None:
        """Remember ``instance``, to call its ``method`` on every :meth:`reset`.

        Held weakly when it can be: a scoped or transient service is built
        again and again, and must not be kept alive by being resettable. When
        a weakly held instance is collected the entry is dropped immediately,
        so a long-running worker never accumulates dead references.
        """
        key = id(instance)
        if key in self._tracked:
            return
        try:
            reference: Callable[[], object | None] = weakref.ref(
                instance,
                lambda _ref, key=key: self._tracked.pop(key, None),
            )
        except TypeError:
            reference = _strong(instance)
        self._tracked[key] = (reference, method)

    async def reset(self) -> None:
        """Call each tracked service's reset method, in tracking order; sync or async."""
        for reference, method in list(self._tracked.values()):
            instance = reference()
            if instance is None:
                continue
            result = cast("object", getattr(instance, method)())
            if inspect.isawaitable(result):
                await result


def _strong(instance: object) -> Callable[[], object]:
    def get() -> object:
        return instance

    return get
