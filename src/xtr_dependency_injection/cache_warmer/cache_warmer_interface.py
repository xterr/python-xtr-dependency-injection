"""A service the kernel runs at boot while the cache is cold, and the cache commands run."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .warmable_interface import WarmableInterface

__all__ = ["CacheWarmerInterface"]


@runtime_checkable
class CacheWarmerInterface(WarmableInterface, Protocol):
    """Fills one part of the application's cache.

    A service implementing this interface is autoconfigured with the
    ``kernel.cache_warmer`` tag, and the kernel's
    :class:`~xtr_dependency_injection.cache_warmer.CacheWarmerAggregate` runs it.
    One that is not optional runs when the kernel boots with a cold cache;
    every one runs on ``cache:warmup`` and ``cache:clear``.
    """

    def is_optional(self) -> bool:
        """Tell whether this warmer may be skipped.

        A warmer whose cache the application can also fill bit by bit, the
        first time each piece is needed, is optional: skipping it costs a
        slower first use, never a wrong answer. One whose cache the
        application cannot do without is not.
        """
        ...
