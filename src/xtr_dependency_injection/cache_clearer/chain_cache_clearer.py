"""Every cache clearer of the application, run as one."""

from __future__ import annotations

from typing import TYPE_CHECKING, final

from typing_extensions import override

from .cache_clearer_interface import CacheClearerInterface

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

__all__ = ["ChainCacheClearer"]


@final
class ChainCacheClearer(CacheClearerInterface):
    """Runs several cache clearers in order, as a single one."""

    __slots__ = ("_clearers",)

    def __init__(self, clearers: Iterable[CacheClearerInterface] = ()) -> None:
        """Run ``clearers``, in the order given."""
        self._clearers: tuple[CacheClearerInterface, ...] = tuple(clearers)

    @override
    async def clear(self, cache_dir: Path) -> None:
        """Run every clearer, one after another, in order."""
        for clearer in self._clearers:
            await clearer.clear(cache_dir)
