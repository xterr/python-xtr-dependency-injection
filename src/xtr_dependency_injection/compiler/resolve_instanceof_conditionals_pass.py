"""Applying the autoconfiguration rules to every non-kernel definition.

A rule applies to a definition when the definition's built type has the
rule's ``type_`` in its ``__mro__``. The rules come from
``ContainerBuilder.register_for_autoconfiguration`` and from the
``@autoconfigure`` / ``@autoconfigure_tag`` markers
:class:`~xtr_dependency_injection.compiler.register_autoconfigure_attributes_pass.RegisterAutoconfigureAttributesPass`
read. Each contributes tags, a lifetime and, for a class definition, a factory.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast, final

from xtr_dependency_injection.exception import ConfigProviderError
from xtr_dependency_injection.exception._naming import qualified_name

from ._state import state_of
from ._wireup_bridge import built_type, key_type
from .register_autoconfigure_attributes_pass import CALLABLE_ATTRS

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from xtr_dependency_injection.builder.autoconfigure_rule import AutoconfigureRule
    from xtr_dependency_injection.builder.container_builder import ContainerBuilder
    from xtr_dependency_injection.builder.definition import Definition

__all__ = ["ResolveInstanceofConditionalsPass"]


@final
class ResolveInstanceofConditionalsPass:
    """Applies every matching autoconfiguration rule to each definition.

    Kernel-origin definitions are never autoconfigured, and a tag already on a
    definition wins over the rule's — explicit stays.
    """

    __slots__ = ()

    def process(self, builder: ContainerBuilder) -> None:
        """Apply the tags, lifetime and factory of every rule matching a definition.

        Raises:
            ConfigProviderError: If a rule's factory does not return the
                matched class.
        """
        rules = state_of(builder).autoconfigure_rules
        if not rules:
            return
        for definition in builder.get_definitions():
            if definition.origin.kind == "kernel":
                continue
            built = built_type(definition)
            if built is None:
                continue
            for rule in rules:
                if rule.type_ in built.__mro__:
                    _apply(rule, definition, built)


def _apply(rule: AutoconfigureRule, definition: Definition, built: type) -> None:
    for tag_name, attribute_list in rule.tags.items():
        if definition.has_tag(tag_name):
            continue
        for attrs in attribute_list:
            deferred = attrs.get(CALLABLE_ATTRS)
            if deferred is not None:
                computed = cast("Callable[[type], Mapping[str, object]]", deferred)(built)
                _ = definition.add_tag(tag_name, **dict(computed))
            else:
                _ = definition.add_tag(tag_name, **attrs)
    if rule.lifetime is not None:
        definition.lifetime = rule.lifetime
    if rule.factory is not None and definition.kind == "class":
        _replace_with_factory(definition, rule.factory, built)


def _replace_with_factory(
    definition: Definition, factory: Callable[..., object], built: type
) -> None:
    returned = key_type(factory)
    if returned is not built:
        raise ConfigProviderError(
            qualified_name(factory),
            (
                f"@autoconfigure(factory=…) return type {qualified_name(returned)} "
                f"is not the matched class {qualified_name(built)}"
            ),
        )
    definition.provider = factory
    definition.kind = "factory"
