"""Fixture app: @as_service and @as_alias marked classes on an interface."""

from __future__ import annotations

from xtr_dependency_injection.decorator.as_alias import as_alias
from xtr_dependency_injection.decorator.as_service import as_service


class Notifier:
    pass


@as_service()
@as_alias(Notifier)
class EmailNotifier(Notifier):
    pass


@as_service(lifetime="singleton")
def build_widget() -> Widget:
    return Widget()


class Widget:
    pass
