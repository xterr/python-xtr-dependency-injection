"""Something whose cache can be filled ahead of the first request for it."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["WarmableInterface"]


@runtime_checkable
class WarmableInterface(Protocol):
    """Fills its cache on demand, so the first use does not pay for it."""

    async def warm_up(self, cache_dir: Path, build_dir: Path | None = None) -> None:
        """Fill the cache.

        Args:
            cache_dir: Where what is written at run time goes; the application
                may write there again later.
            build_dir: Where what is only ever read goes, so a deploy can ship
                it on a read-only filesystem; often ``cache_dir`` itself.
                ``None`` when the caller gives no such place: write only to
                ``cache_dir`` then.
        """
        ...
