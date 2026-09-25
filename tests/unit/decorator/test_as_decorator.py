from __future__ import annotations

from typing import Annotated

from xtr_dependency_injection.decorator.as_decorator import (
    DecoratorMarker,
    Inner,
    InnerMarker,
    as_decorator,
    decorator_of,
    inner_type_of,
)


class Bus:
    pass


def test_as_decorator_records_target_qualifier_and_priority() -> None:
    @as_decorator(Bus, qualifier="main", priority=2)
    class Tracing:
        def __init__(self, inner: Inner[Bus]) -> None:
            self.inner: Bus = inner

    assert decorator_of(Tracing) == DecoratorMarker(Bus, "main", 2)


def test_an_unmarked_class_is_not_a_decorator() -> None:
    class Plain:
        pass

    assert decorator_of(Plain) is None


def test_inner_is_annotated_with_the_marker() -> None:
    assert Inner[Bus] == Annotated[Bus, InnerMarker()]


def test_inner_type_of_unwraps_inner() -> None:
    assert inner_type_of(Inner[Bus]) is Bus


def test_inner_type_of_ignores_other_annotations() -> None:
    assert inner_type_of(Bus) is None
    assert inner_type_of(Annotated[Bus, "other"]) is None
