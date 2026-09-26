"""Fixture: ``@autoconfigure(factory=…)`` return type mismatches the class."""

from __future__ import annotations

from xtr_dependency_injection.decorator.as_service import as_service
from xtr_dependency_injection.decorator.autoconfigure import autoconfigure


class WrongReturn:
    pass


def wrong_factory() -> WrongReturn:
    return WrongReturn()


@autoconfigure(factory=wrong_factory)
@as_service()
class MismatchedFactory:
    pass
