"""Class-level autoconfiguration markers: ``@autoconfigure`` and ``@autoconfigure_tag``.

Put on a class or interface, they say: every definition whose built type has
this class in its ``__mro__`` (itself included) gets the described tags and,
if the marker asks for it, the described lifetime and factory.
``RegisterAutoconfigureAttributesPass`` reads the markers off scanned
candidates into rules that ``ResolveInstanceofConditionalsPass`` applies
alongside the ``register_for_autoconfiguration`` ones.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final, TypeVar, cast

from xtr_dependency_injection.builder.definition import Lifetime

from ._marker import own_marker, set_marker

__all__ = [
    "AutoconfigureMarker",
    "AutoconfigureTagMarker",
    "TagAttributes",
    "TagEntry",
    "autoconfigure",
    "autoconfigure_of",
    "autoconfigure_tag",
    "autoconfigure_tags_of",
]

T = TypeVar("T", bound=type)

_AUTOCONFIGURE: Final = "__xtr_autoconfigure__"
_AUTOCONFIGURE_TAGS: Final = "__xtr_autoconfigure_tags__"

TagAttributes = Mapping[str, object] | Callable[[type], Mapping[str, object]]
"""A tag's attribute mapping, or a callable computing it from the concrete class."""

TagEntry = str | tuple[str, TagAttributes]
"""One tag: a bare name (no attributes), or ``(name, attributes)``."""


@dataclass(frozen=True, slots=True)
class AutoconfigureMarker:
    """What ``@autoconfigure`` records on a class.

    Attributes:
        tags: The tags to add to every matched definition. Each entry is
            either a bare tag name, or ``(name, attributes)`` where
            ``attributes`` is a mapping or a callable ``type -> mapping``.
        lifetime: If not ``None``, the lifetime given to matched definitions.
        factory: If not ``None``, matched *class* definitions become factory
            definitions whose provider is ``factory``. Its evaluated return
            type must equal the matched class' key type, else
            :class:`ConfigProviderError`.
    """

    tags: tuple[TagEntry, ...] = ()
    lifetime: Lifetime | None = None
    factory: Callable[..., object] | None = None


@dataclass(frozen=True, slots=True)
class AutoconfigureTagMarker:
    """What one ``@autoconfigure_tag`` records — repeatable, one marker per call.

    Attributes:
        name: The tag name; ``None`` means "use the decorated class'
            ``qualified_name``".
        attributes: The attribute mapping to attach to the tag.
    """

    name: str | None = None
    attributes: Mapping[str, object] = field(
        default_factory=lambda: cast("Mapping[str, object]", {})
    )


def autoconfigure(
    *,
    tags: Sequence[TagEntry] = (),
    lifetime: Lifetime | None = None,
    factory: Callable[..., object] | None = None,
) -> Callable[[T], T]:
    """Record a class-level autoconfiguration rule.

    The decorator only records the rule on the class' own namespace —
    ``RegisterAutoconfigureAttributesPass`` consumes it.
    """
    marker = AutoconfigureMarker(tags=tuple(tags), lifetime=lifetime, factory=factory)

    def mark(target: T) -> T:
        return set_marker(target, _AUTOCONFIGURE, marker)

    return mark


def autoconfigure_tag(name: str | None = None, /, **attributes: object) -> Callable[[T], T]:
    """Record a single tag rule on this class.

    Repeatable: several ``@autoconfigure_tag(...)`` on one class accumulate.
    """
    entry = AutoconfigureTagMarker(name=name, attributes=dict(attributes))

    def mark(target: T) -> T:
        existing = cast(
            "tuple[AutoconfigureTagMarker, ...]",
            own_marker(target, _AUTOCONFIGURE_TAGS) or (),
        )
        return set_marker(target, _AUTOCONFIGURE_TAGS, (*existing, entry))

    return mark


def autoconfigure_of(obj: object) -> AutoconfigureMarker | None:
    """Return the ``@autoconfigure`` marker on ``obj``, or ``None``."""
    return cast("AutoconfigureMarker | None", own_marker(obj, _AUTOCONFIGURE))


def autoconfigure_tags_of(obj: object) -> tuple[AutoconfigureTagMarker, ...]:
    """Return every ``@autoconfigure_tag`` marker on ``obj``, in decoration order."""
    return cast(
        "tuple[AutoconfigureTagMarker, ...]",
        own_marker(obj, _AUTOCONFIGURE_TAGS) or (),
    )
