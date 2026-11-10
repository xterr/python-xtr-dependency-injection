"""Handing the kernel's cache warmer aggregate every ``kernel.cache_warmer`` service."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, final

from xtr_dependency_injection.cache_warmer import CacheWarmerAggregate, CacheWarmerInterface

from .priority_tagged_service import alias_by_priority

if TYPE_CHECKING:
    from xtr_dependency_injection.builder.container_builder import ContainerBuilder

__all__ = ["CACHE_WARMER_TAG", "AddCacheWarmerPass"]

CACHE_WARMER_TAG: Final = "kernel.cache_warmer"
"""The tag a cache warmer carries; an optional ``priority`` attribute, higher run first.

A class subclassing ``CacheWarmerInterface`` carries it without being told.
"""


@final
class AddCacheWarmerPass:
    """Hands :class:`CacheWarmerAggregate` every service tagged :data:`CACHE_WARMER_TAG`.

    Registered by the kernel bundle, after every bundle's ``process`` hook, so a
    warmer a bundle tags there runs too.
    """

    __slots__ = ()

    def process(self, builder: ContainerBuilder) -> None:
        """Alias every tagged warmer, in priority order, and give the aggregate their names.

        Raises:
            InvalidDefinitionError: When a tag's ``priority`` is not an integer.
        """
        names = alias_by_priority(builder, CACHE_WARMER_TAG, CacheWarmerInterface)
        _ = builder.get_definition(CacheWarmerAggregate).set_argument("warmer_names", names)
