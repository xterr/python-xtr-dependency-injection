"""Fixture app: ``@as_tagged_item`` where an unprioritised item is placed by ``before``."""

from __future__ import annotations

from xtr_dependency_injection.decorator.as_tagged_item import as_tagged_item


class Plugin:
    def name(self) -> str:
        return type(self).__name__


@as_tagged_item(index="b")
class B(Plugin):
    pass


@as_tagged_item(index="a", before=(B,))
class A(Plugin):
    pass
