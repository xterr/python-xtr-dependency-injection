"""``BeforeAfterSorter``: reorder items to satisfy before/after constraints.

:func:`sort_with_priorities` is what the package exports; :func:`sort`, the
same ordering without priorities, is used by it and by the compiler. Both
share the private :func:`_visit` DFS.

Items are emitted depth-first in seed order, which keeps the seed order
intact wherever the constraints allow it. ``A before B`` and ``B after A``
describe the same edge and yield the same order. References to items that
are not in the seed are ignored: the package declaring them may simply not
be installed. An item referencing itself is ignored too.

Every ordering failure becomes a :class:`ServiceOrderError` carrying the
message verbatim in ``reason``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from xtr_dependency_injection.exception.service_order_error import ServiceOrderError

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

__all__ = ["sort_with_priorities"]


_INT64_MIN: Final = -(2**63)
_INT64_MAX: Final = 2**63 - 1
_STATE_VISITING: Final = 1
_STATE_VISITED: Final = 2


def sort(
    seed: Sequence[str],
    constraints: Mapping[str, Mapping[str, Sequence[str]]],
    aliases: Mapping[str, Sequence[str]] | None = None,
) -> list[str]:
    """Return ``seed`` reordered to satisfy ``constraints``.

    Args:
        seed: Items in the order they would have without any constraint.
        constraints: Per item, an ``"before"``/``"after"`` mapping to a list
            of target names.
        aliases: Alternative names, each designating the items it stands for;
            a name that is not listed here designates the item bearing it.

    Raises:
        ServiceOrderError: When the constraints are cyclic.
    """
    aliases = aliases or {}
    if not constraints:
        return list(seed)

    predecessors: dict[str, list[str]] = {item: [] for item in seed}

    for item, constraint in constraints.items():
        if item not in predecessors:
            continue

        for direction in ("before", "after"):
            for target in constraint.get(direction, ()) or ():
                for target_item in aliases.get(target, [target]):
                    if target_item == item or target_item not in predecessors:
                        continue

                    if direction == "before":
                        predecessors[target_item].append(item)
                    else:
                        predecessors[item].append(target_item)

    sorted_items: list[str] = []
    states: dict[str, int] = {}

    for item in seed:
        _visit(item, predecessors, states, sorted_items)

    return sorted_items


def sort_with_priorities(  # noqa: C901, PLR0912, PLR0915 — the algorithm keeps its shape as one unit.
    priorities: Mapping[str, int | None],
    constraints: Mapping[str, Mapping[str, Sequence[str]]],
    aliases: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, int]:
    """Sort items by priority first, then apply the constraints.

    An explicit priority is a claim: constraints reorder such an item only
    among the items sharing its priority, and a constraint that would need it
    to cross a priority is an error. An item without priority is free: its
    constraints place it, and it adopts the priority its place requires, ``0``
    when that fits.

    Args:
        priorities: Items in their default order, mapped to their declared
            priority, ``None`` when none was declared.
        constraints: See :func:`sort`.
        aliases: See :func:`sort`.

    Returns:
        The items in their final order, mapped to their effective priority.

    Raises:
        ServiceOrderError: When the constraints are cyclic or contradict an
            explicit priority.
    """
    aliases = aliases or {}
    seed: list[str] = list(priorities.keys())
    indexes: dict[str, int] = {item: index for index, item in enumerate(seed)}

    # Stable sort: priority desc, ties by original index asc (missing priority = 0).
    seed.sort(key=lambda item: (-_declared_or_zero(priorities, item), indexes[item]))

    if not constraints:
        return {item: _declared_or_zero(priorities, item) for item in seed}

    # detects cycles before the bounds below are computed, so that a cycle is reported as such
    _ = sort(seed, constraints, aliases)

    # every edge is "$before runs before $after"; a declared priority must already agree with it
    edges: list[tuple[str, str]] = []

    for item, constraint in constraints.items():
        if item not in indexes:
            continue

        for direction in ("before", "after"):
            for target in constraint.get(direction, ()) or ():
                for target_item in aliases.get(target, [target]):
                    if target_item == item or target_item not in indexes:
                        continue

                    edges.append(
                        (item, target_item) if direction == "before" else (target_item, item)
                    )

                    priority = priorities.get(item)
                    if priority is None:
                        continue

                    target_priority = priorities.get(target_item)
                    if target_priority is None:
                        continue

                    if direction == "before" and priority < target_priority:
                        raise ServiceOrderError(
                            _contradiction_message(
                                item,
                                priority,
                                "before",
                                target_item,
                                target_priority,
                                "raise",
                            )
                        )

                    if direction == "after" and priority > target_priority:
                        raise ServiceOrderError(
                            _contradiction_message(
                                item,
                                priority,
                                "after",
                                target_item,
                                target_priority,
                                "lower",
                            )
                        )

    # an item without priority is bounded by the items it must run before (from below) and after
    # (from above), through other free items too, so the bounds are propagated until they settle
    lows: dict[str, int] = {}
    highs: dict[str, int] = {}
    lows_from: dict[str, str] = {}
    highs_from: dict[str, str] = {}

    for item, priority in priorities.items():
        if priority is None:
            lows[item] = _INT64_MIN
            highs[item] = _INT64_MAX

    settled = False
    while not settled:
        settled = True

        for before, after in edges:
            if before in lows:
                low = priorities.get(after)
                if low is None:
                    low = lows.get(after, _INT64_MIN)
                if low > lows[before]:
                    lows[before] = low
                    lows_from[before] = after
                    settled = False

            if after in highs:
                high = priorities.get(before)
                if high is None:
                    high = highs.get(before, _INT64_MAX)
                if high < highs[after]:
                    highs[after] = high
                    highs_from[after] = before
                    settled = False

    resolved: dict[str, int] = {}

    for item, priority in priorities.items():
        if priority is not None:
            resolved[item] = priority
        elif lows[item] > highs[item]:
            raise ServiceOrderError(
                _unsatisfiable_message(
                    item, lows[item], lows_from[item], highs[item], highs_from[item]
                )
            )
        else:
            resolved[item] = min(highs[item], max(lows[item], 0))

    # with every item in the bucket its constraints allow, the sort only reorders inside buckets
    seed.sort(key=lambda item: (-resolved[item], indexes[item]))
    sorted_items = sort(seed, constraints, aliases)

    previous: str | None = None
    for item in sorted_items:
        if previous is not None and resolved[item] > resolved[previous]:
            raise ServiceOrderError(
                _ordering_message(previous, resolved[previous], item, resolved[item])
            )
        previous = item

    return {item: resolved[item] for item in sorted_items}


def _declared_or_zero(priorities: Mapping[str, int | None], item: str) -> int:
    """Return ``item``'s declared priority, or ``0`` when it has none."""
    priority = priorities.get(item)
    return 0 if priority is None else priority


def _visit(
    item: str,
    predecessors: Mapping[str, Sequence[str]],
    states: dict[str, int],
    sorted_items: list[str],
) -> None:
    """Emit ``item`` after its predecessors, depth-first, with an explicit stack.

    Iterative so a long chain of constraints cannot exhaust the interpreter's
    recursion limit.
    """
    if states.get(item, 0) == _STATE_VISITED:
        return

    states[item] = _STATE_VISITING
    path: list[str] = [item]
    stack: list[tuple[str, Iterator[str]]] = [(item, iter(predecessors[item]))]

    while stack:
        current, pending = stack[-1]
        for predecessor in pending:
            state = states.get(predecessor, 0)
            if state == _STATE_VISITED:
                continue
            if state == _STATE_VISITING:
                cycle = [*path[path.index(predecessor) :], predecessor]
                joined = '" -> "'.join(cycle)
                raise ServiceOrderError(
                    f'Cycle detected in the "before"/"after" constraints: "{joined}".'
                )
            states[predecessor] = _STATE_VISITING
            path.append(predecessor)
            stack.append((predecessor, iter(predecessors[predecessor])))
            break
        else:
            _ = stack.pop()
            _ = path.pop()
            states[current] = _STATE_VISITED
            sorted_items.append(current)


def _contradiction_message(  # noqa: PLR0913, PLR0917 — six discrete fields for the error message.
    item: str,
    priority: int,
    direction: str,
    target_item: str,
    target_priority: int,
    verb: str,
) -> str:
    bound = "or more" if verb == "raise" else "or less"
    return (
        f'The priority of "{item}" ({priority}) contradicts its "{direction}" constraint on '
        f'"{target_item}" ({target_priority}): {verb} it to {target_priority} {bound}, remove it,'
        f" or drop the constraint."
    )


def _unsatisfiable_message(item: str, low: int, low_from: str, high: int, high_from: str) -> str:
    return (
        f'The "before"/"after" constraints on "{item}" cannot be satisfied: it would need a '
        f'priority of at least {low} to run before "{low_from}" and at most {high} to run after '
        f'"{high_from}".'
    )


def _ordering_message(previous: str, previous_priority: int, item: str, priority: int) -> str:
    return (
        f'The "before"/"after" constraints put "{previous}" (priority {previous_priority}) ahead '
        f'of "{item}" (priority {priority}), which their priorities do not allow.'
    )
