"""Reading ``@autoconfigure`` / ``@autoconfigure_tag`` markers off scanned classes.

The pass reads the ``@autoconfigure`` / ``@autoconfigure_tag`` markers a
class declares and turns them into autoconfiguration rules. Each scanned
class carrying either marker becomes one :class:`AutoconfigureRule` (keyed
on the class itself), which :mod:`resolve_instanceof_conditionals_pass`
then applies to definitions.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Final, cast

from xtr_dependency_injection.builder.autoconfigure_rule import AutoconfigureRule
from xtr_dependency_injection.decorator.autoconfigure import (
    AutoconfigureMarker,
    autoconfigure_of,
    autoconfigure_tags_of,
)
from xtr_dependency_injection.exception._naming import qualified_name

if TYPE_CHECKING:
    from collections.abc import Sequence

    from xtr_dependency_injection.scan.scanned_object import ScannedObject

__all__ = ["CALLABLE_ATTRS", "collect_marker_rules"]

CALLABLE_ATTRS: Final = "__xtr_autoconfigure_callable__"
"""Sentinel key under which a deferred tag-attribute callable is stashed.

Written by :func:`collect_marker_rules` and read by the
``resolve_instanceof_conditionals_pass`` when it applies a rule, so the two
share one spelling.
"""


def collect_marker_rules(
    candidates: Sequence[ScannedObject],
) -> dict[type, tuple[AutoconfigureMarker, AutoconfigureRule]]:
    """Return a rule per scanned class carrying ``@autoconfigure`` or ``@autoconfigure_tag``."""
    collected: dict[type, tuple[AutoconfigureMarker, AutoconfigureRule]] = {}
    for candidate in candidates:
        obj = candidate.obj
        if not isinstance(obj, type):
            continue
        marker = autoconfigure_of(obj)
        tag_markers = autoconfigure_tags_of(obj)
        if marker is None and not tag_markers:
            continue
        rule = AutoconfigureRule(type_=obj)
        effective = marker if marker is not None else AutoconfigureMarker()
        if effective.lifetime is not None:
            rule.lifetime = effective.lifetime
        for entry in effective.tags:
            if isinstance(entry, str):
                rule.tags.setdefault(entry, []).append({})
            else:
                tag_name, attrs = entry
                rule.tags.setdefault(tag_name, []).append(_as_tag_attrs(attrs))
        for tm in tag_markers:
            name = tm.name if tm.name is not None else qualified_name(obj)
            rule.tags.setdefault(name, []).append(dict(tm.attributes))
        collected[obj] = (effective, rule)
    return collected


def _as_tag_attrs(attrs: object) -> dict[str, object]:
    """Normalize a tag-attribute value into a dict, deferring callables via a sentinel."""
    if callable(attrs) and not isinstance(attrs, Mapping):
        return {CALLABLE_ATTRS: attrs}
    return dict(cast("Mapping[str, object]", attrs))
