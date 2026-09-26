"""Fixture app: ``@as_tagged_item`` where an explicit priority contradicts a ``before``."""

from __future__ import annotations

from xtr_dependency_injection.decorator.as_tagged_item import as_tagged_item


class Plugin:
    def name(self) -> str:
        return type(self).__name__


@as_tagged_item(index="b", priority=5)
class B(Plugin):
    pass


@as_tagged_item(index="a", priority=1, before=(B,))
class A(Plugin):
    pass
