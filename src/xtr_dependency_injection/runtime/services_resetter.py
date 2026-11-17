"""Resetting singletons between units of work — the ``kernel.reset`` tag.

A long-running worker handles one message after another with the same
singletons. A singleton that caches what it can work out again declares a
reset method; the worker calls :meth:`ServicesResetter.reset` after each
message, and only singletons that were actually built are reset. A scoped or
transient service is never reset: it lives and dies with its unit of work.

A worker may handle several messages at once, so a reset runs while other
units are still under way. A singleton's reset must be safe then: it clears
only what can be worked out again, never state a running unit reads. What
belongs to one unit of work is kept by that unit — in a scoped service — not
by a singleton waiting to be reset.
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
    """Tracks built resettable singletons and resets them on demand."""

    __slots__ = ("_tracked",)

    def __init__(self) -> None:
        """Track nothing yet: services are tracked as the container builds them."""
        self._tracked: dict[int, tuple[Callable[[], object | None], str]] = {}

    def track(self, instance: object, method: str) -> None:
        """Remember ``instance``, to call its ``method`` on every :meth:`reset`.

        Held weakly when it can be, so being resettable keeps nothing alive:
        when a weakly held instance is collected the entry is dropped
        immediately, so a long-running worker never accumulates dead
        references.

        An instance that cannot be weak-referenced — one whose ``__slots__``
        omit ``__weakref__`` — is instead held strongly, by a closure over it,
        so it lives as long as the resetter does. Both cases key the entry by
        ``id(instance)`` to skip a repeat of the same instance; that
        deduplication is exact because a strongly held instance's ``id`` cannot
        be reused while it is tracked, and a weakly held one's entry is gone
        (dropped by the collection callback) before its ``id`` could be.
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
        """Call each tracked service's reset method, in tracking order; sync or async.

        Every service is reset, whichever of them fail: one left holding the
        last unit of work's caches would bleed them into the next. Units of
        work still running are not waited for: each reset must be safe while
        they run.

        Raises:
            ExceptionGroup: Of what every failing reset raised, once all ran.
        """
        errors: list[Exception] = []
        for reference, method in list(self._tracked.values()):
            instance = reference()
            if instance is None:
                continue
            try:
                result = cast("object", getattr(instance, method)())
                if inspect.isawaitable(result):
                    await result
            except Exception as error:  # noqa: BLE001 — collected, and raised once every service is reset
                errors.append(error)
        if errors:
            raise ExceptionGroup("services failed to reset", errors)


def _strong(instance: object) -> Callable[[], object]:
    def get() -> object:
        return instance

    return get
