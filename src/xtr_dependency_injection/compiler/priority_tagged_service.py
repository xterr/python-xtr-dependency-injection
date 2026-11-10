"""One stable priority sort, shared by the kernel and its built-in passes.

Orders items by a numeric priority, highest first, keeping insertion order
for ties. Every place that orders by "priority descending, ties by collection
order" — the compiler-pass stage sort, the ``@on_boot`` / ``@on_shutdown``
hooks, the decoration stack — goes through :func:`by_priority`. Python's
``sorted`` is stable, so the caller only supplies how to read a priority and
a collection order from each item; equal priorities keep the order they were
collected in.

:func:`alias_by_priority` orders the services carrying a tag the same way,
for a pass that hands them to one service as a collection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

from xtr_dependency_injection.exception import InvalidDefinitionError

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence

    from xtr_dependency_injection.builder.container_builder import ContainerBuilder
    from xtr_dependency_injection.builder.definition import ServiceKey

__all__ = ["alias_by_priority", "by_priority"]

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


def alias_by_priority(builder: ContainerBuilder, tag: str, interface: type) -> list[str]:
    """Alias every service tagged ``tag`` under ``interface``, and return the qualifiers, in order.

    Each service is aliased under ``(interface, "<tag>.<index>")``, so a
    factory taking a ``ServiceLocator`` of ``interface`` and the returned
    qualifiers builds them in order, without being handed the container. The
    order is the tag's ``priority`` attribute, highest first — the highest of
    them when the service carries the tag more than once — else the
    definition's own priority, else 0; ties keep definition order. A service
    decorating another is left out: it answers as the service it decorates,
    which carries the tag.

    Raises:
        InvalidDefinitionError: When a tag's ``priority`` is not an integer.
    """
    ranked: list[tuple[int, ServiceKey, int]] = []
    for order, (key, attribute_list) in enumerate(builder.find_tagged_service_ids(tag).items()):
        definition = builder.get_definition(*key)
        if definition.decorates is None:
            fallback = definition.priority or 0
            ranked.append((order, key, _priority(key, tag, attribute_list, fallback)))

    names: list[str] = []
    ordered = by_priority(ranked, priority=lambda one: one[2], order=lambda one: one[0])
    for index, (_, (service, qualifier), _) in enumerate(ordered):
        name = f"{tag}.{index}"
        builder.set_alias(interface, service, alias_qualifier=name, target_qualifier=qualifier)
        names.append(name)
    return names


def _priority(
    key: ServiceKey, tag: str, attribute_list: Sequence[Mapping[str, object]], fallback: int
) -> int:
    priorities: list[int] = []
    for attributes in attribute_list:
        if "priority" not in attributes:
            continue
        priority = attributes["priority"]
        if not isinstance(priority, int) or isinstance(priority, bool):
            raise InvalidDefinitionError(key, f'tag "{tag}" has a priority that is not an integer')
        priorities.append(priority)
    return max(priorities, default=fallback)
