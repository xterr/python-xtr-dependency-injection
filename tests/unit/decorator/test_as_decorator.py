from __future__ import annotations

from typing import Annotated

from xtr_dependency_injection.decorator.as_decorator import (
    AutowireDecorated,
    DecoratorMarker,
    OnInvalid,
    as_decorator,
    decorator_of,
)


class Bus:
    pass


def test_as_decorator_records_target_qualifier_priority_and_default_on_invalid() -> None:
    @as_decorator(Bus, qualifier="main", priority=2)
    class Tracing:
        def __init__(self, inner: Annotated[Bus, AutowireDecorated()]) -> None:
            self.inner: Bus = inner

    assert decorator_of(Tracing) == DecoratorMarker(Bus, "main", 2, OnInvalid.EXCEPTION)


def test_as_decorator_records_the_on_invalid_option() -> None:
    @as_decorator(Bus, on_invalid=OnInvalid.NULL)
    class Tracing:
        def __init__(self, inner: Annotated[Bus | None, AutowireDecorated()]) -> None:
            self.inner: Bus | None = inner

    marker = decorator_of(Tracing)
    assert marker is not None
    assert marker.on_invalid is OnInvalid.NULL


def test_an_unmarked_class_is_not_a_decorator() -> None:
    class Plain:
        pass

    assert decorator_of(Plain) is None
