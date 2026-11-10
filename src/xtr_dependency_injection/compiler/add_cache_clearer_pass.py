"""Handing the kernel's chain cache clearer every ``kernel.cache_clearer`` service."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, final

from xtr_dependency_injection.cache_clearer import CacheClearerInterface, ChainCacheClearer

from .priority_tagged_service import alias_by_priority

if TYPE_CHECKING:
    from xtr_dependency_injection.builder.container_builder import ContainerBuilder

__all__ = ["CACHE_CLEARER_TAG", "AddCacheClearerPass"]

CACHE_CLEARER_TAG: Final = "kernel.cache_clearer"
"""The tag a cache clearer carries; an optional ``priority`` attribute, higher run first.

A class subclassing ``CacheClearerInterface`` carries it without being told.
"""


@final
class AddCacheClearerPass:
    """Hands :class:`ChainCacheClearer` every service tagged :data:`CACHE_CLEARER_TAG`.

    Registered by the kernel bundle, after every bundle's ``process`` hook, so a
    clearer a bundle tags there runs too.
    """

    __slots__ = ()

    def process(self, builder: ContainerBuilder) -> None:
        """Alias every tagged clearer, in priority order, and give the chain their names.

        Raises:
            InvalidDefinitionError: When a tag's ``priority`` is not an integer.
        """
        names = alias_by_priority(builder, CACHE_CLEARER_TAG, CacheClearerInterface)
        _ = builder.get_definition(ChainCacheClearer).set_argument("clearer_names", names)
