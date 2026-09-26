"""Reading ``@autoconfigure`` / ``@autoconfigure_tag`` markers off scanned classes into rules.

Each scanned class carrying either marker becomes one
:class:`AutoconfigureRule` keyed on the class itself, appended after the rules
bundles registered with ``register_for_autoconfiguration``;
:class:`~xtr_dependency_injection.compiler.resolve_instanceof_conditionals_pass.ResolveInstanceofConditionalsPass`
then applies both to the definitions.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Final, cast, final

from xtr_dependency_injection.builder.autoconfigure_rule import AutoconfigureRule
from xtr_dependency_injection.decorator.autoconfigure import (
    AutoconfigureMarker,
    autoconfigure_of,
    autoconfigure_tags_of,
)
from xtr_dependency_injection.exception._naming import qualified_name

from ._state import state_of

if TYPE_CHECKING:
    from xtr_dependency_injection.builder.container_builder import ContainerBuilder

__all__ = ["CALLABLE_ATTRS", "RegisterAutoconfigureAttributesPass"]

CALLABLE_ATTRS: Final = "__xtr_autoconfigure_callable__"
"""Key under which a tag-attribute callable is stashed until the built class is known.

Written here and read by ``ResolveInstanceofConditionalsPass`` when it applies
a rule, so the two share one spelling.
"""


@final
class RegisterAutoconfigureAttributesPass:
    """Turns the autoconfiguration markers of every scanned class into a rule for it."""

    __slots__ = ()

    def process(self, builder: ContainerBuilder) -> None:
        """Append a rule for every scanned class carrying ``@autoconfigure`` or a tag marker."""
        state = state_of(builder)
        for candidate in state.candidates:
            rule = _rule_for(candidate.obj)
            if rule is not None:
                state.autoconfigure_rules.append(rule)


def _rule_for(obj: object) -> AutoconfigureRule | None:
    if not isinstance(obj, type):
        return None
    marker = autoconfigure_of(obj)
    tag_markers = autoconfigure_tags_of(obj)
    if marker is None and not tag_markers:
        return None
    effective = marker if marker is not None else AutoconfigureMarker()
    rule = AutoconfigureRule(type_=obj, lifetime=effective.lifetime, factory=effective.factory)
    for entry in effective.tags:
        if isinstance(entry, str):
            _ = rule.add_tag(entry)
        else:
            tag_name, attrs = entry
            rule.tags.setdefault(tag_name, []).append(_as_tag_attrs(attrs))
    for tag_marker in tag_markers:
        name = tag_marker.name if tag_marker.name is not None else qualified_name(obj)
        _ = rule.add_tag(name, **tag_marker.attributes)
    return rule


def _as_tag_attrs(attrs: object) -> dict[str, object]:
    """Normalize a tag-attribute value into a dict, deferring a callable under a sentinel."""
    if callable(attrs) and not isinstance(attrs, Mapping):
        return {CALLABLE_ATTRS: attrs}
    return dict(cast("Mapping[str, object]", attrs))
