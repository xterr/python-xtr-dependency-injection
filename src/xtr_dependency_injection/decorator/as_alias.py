"""Marking a class as an alias of another registered service.

Repeatable — one call per alias. An ``@as_alias(Iface)`` on a class
registers the class as a service
(if not already marked) AND records an alias ``Iface -> class``. Every call
appends one alias, so a class may serve under several interfaces.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable
from dataclasses import dataclass
from typing import Final, TypeVar, cast

from ._marker import own_marker, set_marker

__all__ = ["AliasMarker", "aliases_of", "as_alias"]

T = TypeVar("T", bound=type)

_ALIASES: Final = "__xtr_aliases__"


@dataclass(frozen=True, slots=True)
class AliasMarker:
    """What one ``@as_alias`` call records: an alias type and its qualifier."""

    alias: type
    qualifier: Hashable | None = None


def as_alias(alias: type, *, qualifier: Hashable | None = None) -> Callable[[T], T]:
    """Register the decorated class under ``(alias, qualifier)`` in addition to its own key.

    Repeatable: every call appends one alias. The decorated class is also
    registered under its own type as a service, when it is not otherwise
    marked.
    """

    def mark(target: T) -> T:
        existing = cast("tuple[AliasMarker, ...] | None", own_marker(target, _ALIASES)) or ()
        new = (*existing, AliasMarker(alias=alias, qualifier=qualifier))
        return set_marker(target, _ALIASES, new)

    return mark


def aliases_of(obj: object) -> tuple[AliasMarker, ...]:
    """Return the tuple of ``AliasMarker`` recorded on ``obj``, or ``()``."""
    return cast("tuple[AliasMarker, ...] | None", own_marker(obj, _ALIASES)) or ()
