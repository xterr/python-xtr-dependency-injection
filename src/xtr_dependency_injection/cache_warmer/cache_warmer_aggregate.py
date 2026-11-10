"""Every cache warmer of the application, run as one."""

from __future__ import annotations

from typing import TYPE_CHECKING, final

from typing_extensions import override

from .cache_warmer_interface import CacheWarmerInterface

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

__all__ = ["CacheWarmerAggregate"]


@final
class CacheWarmerAggregate(CacheWarmerInterface):
    """Runs several cache warmers in order, as a single one.

    Only the warmers that are not optional run, until
    :meth:`enable_optional_warmers` lets the optional ones run too;
    :meth:`enable_only_optional_warmers` runs nothing but those.
    """

    __slots__ = ("_only_optionals_enabled", "_optionals_enabled", "_warmers")

    def __init__(self, warmers: Iterable[CacheWarmerInterface] = ()) -> None:
        """Run ``warmers``, in the order given."""
        self._warmers: tuple[CacheWarmerInterface, ...] = tuple(warmers)
        self._optionals_enabled = False
        self._only_optionals_enabled = False

    def enable_optional_warmers(self) -> None:
        """Run the optional warmers too."""
        self._optionals_enabled = True

    def enable_only_optional_warmers(self) -> None:
        """Run the optional warmers, and none of the others."""
        self._optionals_enabled = True
        self._only_optionals_enabled = True

    @override
    async def warm_up(self, cache_dir: Path, build_dir: Path | None = None) -> None:
        """Run every enabled warmer, one after another, in order."""
        for warmer in self._warmers:
            optional = warmer.is_optional()
            if optional and not self._optionals_enabled:
                continue
            if not optional and self._only_optionals_enabled:
                continue
            await warmer.warm_up(cache_dir, build_dir)

    @override
    def is_optional(self) -> bool:
        """Never: the aggregate is what runs the warmers that are not optional either."""
        return False
