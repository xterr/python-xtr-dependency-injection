"""A service the ``cache:clear`` command runs."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["CacheClearerInterface"]


@runtime_checkable
class CacheClearerInterface(Protocol):
    """Empties a cache that removing the cache directory does not reach.

    A cache kept elsewhere — on a server, in a directory of its own —
    survives the cache directory being removed. A service implementing this
    interface is autoconfigured with the ``kernel.cache_clearer`` tag, and the
    kernel's :class:`~xtr_dependency_injection.cache_clearer.ChainCacheClearer`
    runs it.
    """

    async def clear(self, cache_dir: Path) -> None:
        """Empty the cache.

        Args:
            cache_dir: The cache directory being cleared.
        """
        ...
