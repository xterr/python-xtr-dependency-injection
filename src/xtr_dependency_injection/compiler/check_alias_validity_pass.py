"""Validating that an alias resolves to a service implementing the alias type.

Injecting the alias hands out the target's instance, so a class definition
whose class is not a subclass of the alias type would be a type error at
runtime. Registered by the kernel bundle.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, final

from xtr_dependency_injection.exception import InvalidDefinitionError
from xtr_dependency_injection.exception._naming import qualified_name

if TYPE_CHECKING:
    from xtr_dependency_injection.builder.container_builder import ContainerBuilder

__all__ = ["CheckAliasValidityPass"]


@final
class CheckAliasValidityPass:
    """Fails the build on an alias whose target class does not implement it.

    Only a target that is a class definition is checked: a factory's or an
    instance's type is what it is registered under. A protocol that cannot be
    checked at runtime, or a generic alias, is skipped.
    """

    __slots__ = ()

    def process(self, builder: ContainerBuilder) -> None:
        """Check every alias against the class of the definition it points at.

        Raises:
            InvalidDefinitionError: If a target class does not implement its
                alias type.
        """
        for alias_key, (target_type, target_qualifier) in builder.get_aliases().items():
            if not builder.has_definition(target_type, target_qualifier):
                continue
            target = builder.get_definition(target_type, target_qualifier)
            if target.kind != "class" or not isinstance(target.provider, type):
                continue
            alias_type = alias_key[0]
            try:
                implements = issubclass(target.provider, alias_type)
            except TypeError:
                continue
            if not implements:
                raise InvalidDefinitionError(
                    alias_key,
                    (
                        f"the alias references class {qualified_name(target.provider)}, "
                        f"which does not implement {qualified_name(alias_type)}"
                    ),
                )
