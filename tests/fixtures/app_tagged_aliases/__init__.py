"""Fixture app: tagged items collected through ``@as_alias``, declared out of order on purpose.

The collection order must come from ``priority``, ``before`` and ``after`` on the classes —
``gamma, alpha, delta, beta`` here — never from the order the aliases are declared in.
"""

from __future__ import annotations

from collections.abc import Hashable, Mapping, Sequence

from xtr_dependency_injection import as_alias, as_service, as_tagged_item


class Step:
    pass


@as_alias(Step, qualifier="beta")
@as_tagged_item(index="beta", priority=-10)
class Beta(Step):
    pass


@as_alias(Step, qualifier="alpha")
@as_tagged_item(index="alpha", priority=0)
class Alpha(Step):
    pass


@as_alias(Step, qualifier="delta")
@as_tagged_item(index="delta", after=[Alpha])
class Delta(Step):
    pass


@as_alias(Step, qualifier="gamma")
@as_tagged_item(index="gamma", before=[Alpha])
class Gamma(Step):
    pass


@as_service
class Pipeline:
    def __init__(self, steps: Sequence[Step], by_index: Mapping[Hashable, Step]) -> None:
        self.steps: list[str] = [type(step).__name__ for step in steps]
        self.indexes: list[Hashable] = list(by_index)
