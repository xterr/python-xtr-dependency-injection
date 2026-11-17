"""Two unit participants journaling each unit's edges, and a scoped resource its teardown.

A test empties :data:`JOURNAL` and names, in :data:`FAILING`, the hooks that
must raise: ``"First.unit_began"``, ``"Second.unit_ended"`` and so on.
"""

from __future__ import annotations

from collections.abc import (
    AsyncIterator,
)
from typing import ClassVar, final

from xtr_dependency_injection import as_service, autoconfigure

__all__ = ["FAILING", "JOURNAL", "First", "Participant", "Resource", "Second", "resource"]

JOURNAL: list[str] = []
"""Every unit edge and teardown, in the order they happened."""

FAILING: set[str] = set()
"""The hooks, as ``"<class>.<hook>"``, that raise instead of journaling."""


@autoconfigure(tags=[("kernel.unit_participant", {})])
class Participant:
    """Journals each unit it is told of, under a token of its own per unit."""

    name: ClassVar[str] = ""

    def __init__(self) -> None:
        self.issued: int = 0

    def unit_began(self) -> object | None:
        self._fail_if("unit_began")
        self.issued += 1
        token = f"{self.name}-{self.issued}"
        JOURNAL.append(f"began {token}")
        return token

    def unit_ended(self, token: object | None) -> None:
        self._fail_if("unit_ended")
        JOURNAL.append(f"ended {token}")

    def _fail_if(self, hook: str) -> None:
        qualified = f"{type(self).__qualname__}.{hook}"
        if qualified in FAILING:
            raise RuntimeError(qualified)


@final
@as_service
class First(Participant):
    """Told first that a unit began, last that it ended."""

    name = "first"


@final
@as_service
class Second(Participant):
    """Told second that a unit began, first that it ended."""

    name = "second"


@final
class Resource:
    """A scoped service whose teardown is journaled."""


@as_service(lifetime="scoped")
async def resource() -> AsyncIterator[Resource]:
    """Hand out one per unit, journaling its teardown."""
    yield Resource()
    JOURNAL.append("teardown")
