from __future__ import annotations

import pytest

from xtr_dependency_injection.decorator.as_decorator import Inner, inner_parameter_of
from xtr_dependency_injection.exception import DecoratorSignatureError


class Bus:
    pass


class Other:
    pass


class Tracing:
    def __init__(self, inner: Inner[Bus], name: str = "x") -> None:
        self.inner: Bus = inner
        self.name: str = name


class NoInner:
    def __init__(self, bus: Bus) -> None:
        self.bus: Bus = bus


class TwoInners:
    def __init__(self, first: Inner[Bus], second: Inner[Bus]) -> None:
        self.first: Bus = first
        self.second: Bus = second


class WrongType:
    def __init__(self, inner: Inner[Other]) -> None:
        self.inner: Other = inner


def tracing(inner: Inner[Bus]) -> Bus:
    return inner


def test_the_inner_parameter_of_a_class_is_found() -> None:
    assert inner_parameter_of(Tracing, Bus) == "inner"


def test_the_inner_parameter_of_a_function_is_found() -> None:
    assert inner_parameter_of(tracing, Bus) == "inner"


def test_no_inner_parameter_is_refused() -> None:
    with pytest.raises(DecoratorSignatureError, match="exactly one Inner"):
        _ = inner_parameter_of(NoInner, Bus)


def test_two_inner_parameters_are_refused() -> None:
    with pytest.raises(DecoratorSignatureError, match="not 2"):
        _ = inner_parameter_of(TwoInners, Bus)


def test_an_inner_of_another_type_is_refused() -> None:
    with pytest.raises(DecoratorSignatureError, match="must be of the decorated type"):
        _ = inner_parameter_of(WrongType, Bus)
