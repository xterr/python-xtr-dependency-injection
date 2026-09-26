"""One stable priority sort, shared by the kernel and its built-in passes.

Orders items by a numeric priority, highest first, keeping insertion order
for ties. Every place that orders by "priority descending, ties by collection
order" — the compiler-pass stage sort, the ``@on_boot`` / ``@on_shutdown``
hooks, the decoration stack — goes through :func:`by_priority`. Python's
``sorted`` is stable, so the caller only supplies how to read a priority and
a collection order from each item; equal priorities keep the order they were
collected in.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

__all__ = ["by_priority"]

_T = TypeVar("_T")


def by_priority(
    items: Iterable[_T],
    *,
    priority: Callable[[_T], int],
    order: Callable[[_T], int],
) -> list[_T]:
    """Return ``items`` by ``priority`` descending, ties broken by ``order`` ascending.

    A stable sort: two items of equal priority keep their relative order,
    which for a collection order is the order they were collected in.
    """
    return sorted(items, key=lambda item: (-priority(item), order(item)))
