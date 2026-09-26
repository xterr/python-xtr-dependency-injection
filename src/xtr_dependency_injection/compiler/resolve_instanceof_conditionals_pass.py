"""Applying the nominal autoconfigure rules to every non-kernel definition.

Resolves the accumulated subclass-conditional rules onto matching
definitions. The attribute-based autoconfigurators run first (in the
kernel's autoconfigure step); this module holds the resolution — the
subclass rules from ``register_for_autoconfiguration`` plus the
``@autoconfigure`` / ``@autoconfigure_tag`` markers read by
:mod:`~xtr_dependency_injection.compiler.register_autoconfigure_attributes_pass`
— turned into per-definition tags, lifetimes and factory swaps.

The pass reads the ``@autoconfigure`` markers and applies both rule sources
in one loop: the reading lives in ``register_autoconfigure_attributes_pass``
and the resolution here, and they share one application.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from xtr_dependency_injection.compiler._wireup_bridge import built_type, key_type
from xtr_dependency_injection.compiler.register_autoconfigure_attributes_pass import (
    CALLABLE_ATTRS,
    collect_marker_rules,
)
from xtr_dependency_injection.exception import ConfigProviderError
from xtr_dependency_injection.exception._naming import qualified_name

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from xtr_dependency_injection.builder.autoconfigure_rule import AutoconfigureRule
    from xtr_dependency_injection.builder.definition import Definition
    from xtr_dependency_injection.builder.service_configurator import BuildState
    from xtr_dependency_injection.scan.scanned_object import ScannedObject

__all__ = ["apply_autoconfigure_rules"]


def apply_autoconfigure_rules(state: BuildState, candidates: Sequence[ScannedObject]) -> None:
    """Apply every nominal autoconfigure rule to every non-kernel definition.

    Rules come from two sources:

    - ``ContainerBuilder.register_for_autoconfiguration`` — collected into
      ``state.autoconfigure_rules``.
    - ``@autoconfigure`` / ``@autoconfigure_tag`` markers on scanned classes —
      each class turns into a rule keyed on the class itself (read by
      ``register_autoconfigure_attributes_pass``).

    A rule applies to a definition when the definition's built type has the
    rule's ``type_`` in its ``__mro__``. Kernel-origin definitions are never
    autoconfigured; a tag already present on a definition
    wins over the rule's — explicit stays. When a rule carries ``factory``
    (from ``@autoconfigure(factory=…)``), a matched class definition becomes
    a factory definition using that factory.
    """
    rules: list[AutoconfigureRule] = list(state.autoconfigure_rules)
    marker_rules = collect_marker_rules(candidates)
    rules.extend(rule for _marker, rule in marker_rules.values())
    factories: dict[type, Callable[..., object]] = {
        cls: marker.factory
        for cls, (marker, _rule) in marker_rules.items()
        if marker.factory is not None
    }
    if not rules and not factories:
        return
    for definition in list(state.store.entries()):
        if definition.origin.kind == "kernel":
            continue
        built = built_type(definition)
        if built is None:
            continue
        mro = built.__mro__
        for rule in rules:
            if rule.type_ not in mro:
                continue
            _apply_rule_to_definition(rule, definition, built)
        for cls, factory in factories.items():
            if cls in mro:
                _replace_with_factory(state, definition, factory, built)


def _apply_rule_to_definition(rule: AutoconfigureRule, definition: Definition, built: type) -> None:
    """Apply ``rule`` to ``definition`` in place — tags, lifetime."""
    for tag_name, attribute_list in rule.tags.items():
        if definition.has_tag(tag_name):
            continue
        for attrs in attribute_list:
            callable_attrs = attrs.get(CALLABLE_ATTRS)
            if callable_attrs is not None:
                computed = cast("Callable[[type], Mapping[str, object]]", callable_attrs)(built)
                _ = definition.add_tag(tag_name, **dict(computed))
            else:
                _ = definition.add_tag(tag_name, **attrs)
    if rule.lifetime is not None:
        definition.lifetime = rule.lifetime


def _replace_with_factory(
    _state: BuildState,
    definition: Definition,
    factory: Callable[..., object],
    built: type,
) -> None:
    """Replace a matched class definition with a factory definition.

    Validates that the factory's evaluated return type equals ``built``; else
    raises :class:`ConfigProviderError` with both types.
    """
    if definition.kind != "class":
        return
    returned = key_type(factory, None)
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
