from __future__ import annotations

from tests.fixtures.app_scan.helpers import Imported
from xtr_dependency_injection.decorator.as_service import as_service
from xtr_dependency_injection.decorator.exclude import exclude

__all__ = ["Hidden", "Imported", "Marked", "Plain", "plain_function"]


@as_service()
class Marked:
    pass


class Plain:
    pass


def plain_function() -> None:
    pass


@exclude
class Hidden:
    pass


ALIAS = Plain
