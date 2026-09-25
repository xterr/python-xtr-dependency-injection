from __future__ import annotations

from wireup import injectable

from tests.fixtures.app_scan.helpers import Imported
from xtr_dependency_injection.decorator.exclude import exclude

__all__ = ["Hidden", "Imported", "Marked", "Plain", "plain_function"]


@injectable
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
