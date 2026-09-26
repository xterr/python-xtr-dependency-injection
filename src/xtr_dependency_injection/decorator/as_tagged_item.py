"""Marking a class or factory as a tagged item — its index, priority and before/after position.

The decorated class or factory is also registered as a service (marking a
tagged item implies auto-registration), and its ``index`` becomes the
qualifier the container registers it under — the key under which it
appears in ``Mapping[Hashable, T]`` collections. ``priority``, ``before``
and ``after`` land on the :class:`Definition` and are consumed by
:func:`sort_with_priorities` in ``compiler/before_after_sorter.py``.
"""

from __future__ import annotations

from collections.abc import Hashable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final, TypeVar, cast, overload

from ._marker import own_marker, set_marker
from .as_service import ServiceMarker

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ["TaggedItemMarker", "as_tagged_item", "tagged_item_of"]

T = TypeVar("T")

_TAGGED_ITEM: Final = "__xtr_tagged_item__"
_SERVICE: Final = "__xtr_service__"


@dataclass(frozen=True, slots=True)
class TaggedItemMarker:
    """What ``@as_tagged_item`` records: the index and ordering constraints of a tagged item."""

    index: Hashable | None = None
    priority: int | None = None
    before: tuple[type, ...] = field(default_factory=tuple)
    after: tuple[type, ...] = field(default_factory=tuple)


@overload
def as_tagged_item(target: T, /) -> T: ...
@overload
def as_tagged_item(
    *,
    index: Hashable | None = None,
    priority: int | None = None,
    before: Sequence[type] = (),
    after: Sequence[type] = (),
) -> Callable[[T], T]: ...
def as_tagged_item(
    target: T | None = None,
    /,
    *,
    index: Hashable | None = None,
    priority: int | None = None,
    before: Sequence[type] = (),
    after: Sequence[type] = (),
) -> T | Callable[[T], T]:
    """Register the decorated class or factory as a tagged service.

    Can be used bare (``@as_tagged_item``) or called with keyword arguments.

    Args:
        target: The class or factory to mark as a tagged item (when used bare).
        index: The key under which the service appears in ``Mapping[Hashable, T]``
            collections — it becomes the definition's qualifier.
        priority: The item's position in ordered collections; higher first.
            ``None`` lets ``before``/``after`` decide, else they only reorder
            within that priority.
        before: Types this service must precede in tagged collections.
        after: Types this service must follow in tagged collections.
    """
    marker = TaggedItemMarker(
        index=index,
        priority=priority,
        before=tuple(before),
        after=tuple(after),
    )

    def mark(obj: T) -> T:
        obj = set_marker(obj, _TAGGED_ITEM, marker)
        # Marking a tagged item implies auto-registration: if nothing else
        # already marked the object as a service, register it with a
        # singleton lifetime under ``index`` as its qualifier.
        if own_marker(obj, _SERVICE) is None:
            obj = set_marker(obj, _SERVICE, ServiceMarker(lifetime="singleton", qualifier=index))
        return obj

    return mark(target) if target is not None else mark


def tagged_item_of(obj: object) -> TaggedItemMarker | None:
    """Return what ``@as_tagged_item`` recorded on ``obj``, or ``None``."""
    return cast("TaggedItemMarker | None", own_marker(obj, _TAGGED_ITEM))
