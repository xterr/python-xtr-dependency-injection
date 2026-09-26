"""Fixture app: ``@as_tagged_item`` classes with priorities and before/after constraints."""

from __future__ import annotations

from xtr_dependency_injection.decorator.as_tagged_item import as_tagged_item


class Plugin:
    def name(self) -> str:
        return type(self).__name__


@as_tagged_item(index="high", priority=10)
class HighPriority(Plugin):
    pass


@as_tagged_item(index="low", priority=-5)
class LowPriority(Plugin):
    pass
