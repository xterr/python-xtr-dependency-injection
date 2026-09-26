"""Replacing every alias by a definition the engine can register.

The engine has no aliases: every key it knows is a factory. So each alias
becomes a factory definition under the alias key producing the target's own
instance — one instance, reachable under both keys. The alias table stays, so
the report can still say which keys forward to which definition.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, final

from xtr_dependency_injection.builder.definition import Definition, Origin
from xtr_dependency_injection.exception import UnknownServiceError

from .registration import _alias_factory

if TYPE_CHECKING:
    from xtr_dependency_injection.builder.container_builder import ContainerBuilder

__all__ = ["ReplaceAliasByActualDefinitionPass"]


@final
class ReplaceAliasByActualDefinitionPass:
    """Gives every alias a forwarding definition, and fails on a missing target.

    A missing target means an ``@as_alias`` (or a ``set_alias`` / ``alias``)
    naming a service that never existed, or a pass that removed the target
    without its aliases. An alias key that already has a definition of its own
    keeps it.
    """

    __slots__ = ()

    def process(self, builder: ContainerBuilder) -> None:
        """Add a forwarding definition for every alias.

        Raises:
            UnknownServiceError: If an alias target is not defined.
        """
        for alias_key, target_key in builder.get_aliases().items():
            if builder.has_definition(*alias_key):
                continue
            if not builder.has_definition(*target_key):
                raise UnknownServiceError(alias_key, "set_alias")
            target = builder.get_definition(*target_key)
            alias_type, _ = alias_key
            target_type, target_qualifier = target_key
            _ = builder.set_definition(
                Definition(
                    key=alias_key,
                    provider=_alias_factory(alias_type, target_type, target_qualifier),
                    kind="factory",
                    lifetime=target.lifetime,
                    origin=Origin(target.origin.kind, target.origin.name, "alias"),
                )
            )
