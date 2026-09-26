from __future__ import annotations

from typing import Annotated

import pytest

from xtr_dependency_injection.decorator.as_decorator import (
    AutowireDecorated,
    decorated_parameter_of,
)
from xtr_dependency_injection.exception import DecoratorSignatureError


class Bus:
    pass


class Other:
    pass


class Tracing:
    def __init__(self, inner: Annotated[Bus, AutowireDecorated()], name: str = "x") -> None:
        self.inner: Bus = inner
        self.name: str = name


class NullableTracing:
    def __init__(self, inner: Annotated[Bus | None, AutowireDecorated()]) -> None:
        self.inner: Bus | None = inner


class NoInner:
    def __init__(self, bus: Bus) -> None:
        self.bus: Bus = bus


class TwoInners:
    def __init__(
        self,
        first: Annotated[Bus, AutowireDecorated()],
        second: Annotated[Bus, AutowireDecorated()],
    ) -> None:
        self.first: Bus = first
        self.second: Bus = second


class WrongType:
    def __init__(self, inner: Annotated[Other, AutowireDecorated()]) -> None:
        self.inner: Other = inner


class NullableForwardRefTracing:
    def __init__(self, inner: Annotated["Bus | None", AutowireDecorated()]) -> None:  # noqa: UP037
        self.inner: Bus | None = inner


class ForwardRefTracing:
    def __init__(self, inner: Annotated["Bus", AutowireDecorated()]) -> None:  # noqa: UP037
        self.inner: Bus = inner


def tracing(inner: Annotated[Bus, AutowireDecorated()]) -> Bus:
    return inner


def test_the_decorated_parameter_of_a_class_is_found() -> None:
    parameter = decorated_parameter_of(Tracing, Bus)

    assert parameter.name == "inner"
    assert parameter.allows_none is False


def test_the_decorated_parameter_of_a_function_is_found() -> None:
    parameter = decorated_parameter_of(tracing, Bus)

    assert parameter.name == "inner"


def test_a_nullable_decorated_parameter_reports_allows_none() -> None:
    parameter = decorated_parameter_of(NullableTracing, Bus)

    assert parameter.name == "inner"
    assert parameter.allows_none is True


def test_no_autowire_decorated_parameter_is_refused() -> None:
    with pytest.raises(DecoratorSignatureError, match="exactly one"):
        _ = decorated_parameter_of(NoInner, Bus)


def test_two_autowire_decorated_parameters_are_refused() -> None:
    with pytest.raises(DecoratorSignatureError, match="not 2"):
        _ = decorated_parameter_of(TwoInners, Bus)


def test_an_autowire_decorated_of_another_type_is_refused() -> None:
    with pytest.raises(DecoratorSignatureError, match="must be of the decorated type"):
        _ = decorated_parameter_of(WrongType, Bus)


def test_a_string_nested_in_annotated_is_resolved() -> None:
    parameter = decorated_parameter_of(ForwardRefTracing, Bus)

    assert parameter.name == "inner"
    assert parameter.allows_none is False


def test_a_nullable_string_nested_in_annotated_reports_allows_none() -> None:
    parameter = decorated_parameter_of(NullableForwardRefTracing, Bus)

    assert parameter.name == "inner"
    assert parameter.allows_none is True
