"""Pointing every alias straight at the definition its chain ends on.

An alias may target another alias. After this pass every alias targets a key
that is not itself an alias, so later passes and the emitter follow one step;
a chain that loops back on itself is an error here rather than an unknown
service later.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, final

from xtr_dependency_injection.exception import ServiceCircularReferenceError

from ._state import state_of

if TYPE_CHECKING:
    from xtr_dependency_injection.builder.container_builder import ContainerBuilder
    from xtr_dependency_injection.builder.definition import ServiceKey

__all__ = ["ResolveReferencesToAliasesPass"]


@final
class ResolveReferencesToAliasesPass:
    """Collapses alias chains, keeping who contributed each alias."""

    __slots__ = ()

    def process(self, builder: ContainerBuilder) -> None:
        """Retarget every alias to the end of its chain.

        Raises:
            ServiceCircularReferenceError: If an alias chain loops.
        """
        aliases = state_of(builder).aliases
        for alias_key, target_key in list(aliases.items()):
            resolved = _definition_key(aliases, alias_key)
            if resolved != target_key:
                aliases[alias_key] = resolved


def _definition_key(aliases: dict[ServiceKey, ServiceKey], key: ServiceKey) -> ServiceKey:
    seen: list[ServiceKey] = []
    while key in aliases:
        if key in seen:
            raise ServiceCircularReferenceError(key, (*seen[seen.index(key) :], key))
        seen.append(key)
        key = aliases[key]
    return key
