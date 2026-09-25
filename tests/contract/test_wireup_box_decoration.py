"""S4: box-type decoration — lifetimes, inner cleanup, collections, stacking."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from typing import Literal

import pytest
import wireup
from typing_extensions import override

from xtr_dependency_injection.compiler.registration import (
    _box_type,
    _decorating_factory,
    _map_result,
    _synthesize_class_factory,
)

pytestmark = pytest.mark.anyio

Lifetime = Literal["singleton", "scoped", "transient"]


class Greeter:
    def greet(self) -> str:
        return "hello"


class Plain(Greeter):
    def __init__(self) -> None:
        self.closed: bool = False


class Loud(Greeter):
    def __init__(self, inner: Greeter) -> None:
        self.inner: Greeter = inner

    @override
    def greet(self) -> str:
        return self.inner.greet().upper()


class Exclaiming(Greeter):
    def __init__(self, inner: Greeter) -> None:
        self.inner: Greeter = inner

    @override
    def greet(self) -> str:
        return self.inner.greet() + "!"


class Other(Greeter):
    @override
    def greet(self) -> str:
        return "other"


def plain_resource() -> Iterator[Plain]:
    plain = Plain()
    yield plain
    plain.closed = True


def _boxed(factory: Callable[..., object], box: type, lifetime: Lifetime) -> object:
    return wireup.injectable(_map_result(factory, box, provides=box), lifetime=lifetime)


def _decorator(
    decorator: type, box: type, lifetime: Lifetime, qualifier: str | None = None
) -> object:
    factory = _decorating_factory(
        _synthesize_class_factory(decorator), "inner", box, provides=decorator
    )
    return wireup.injectable(factory, as_type=Greeter, lifetime=lifetime, qualifier=qualifier)


def _decorated(lifetime: Lifetime) -> wireup.AsyncContainer:
    box = _box_type(1)
    return wireup.create_async_container(
        injectables=[
            _boxed(_synthesize_class_factory(Plain), box, lifetime),
            _decorator(Loud, box, lifetime),
        ]
    )


async def test_the_decorator_takes_the_original_key() -> None:
    greeter = await _decorated("singleton").get(Greeter)

    assert isinstance(greeter, Loud)
    assert isinstance(greeter.inner, Plain)
    assert greeter.greet() == "HELLO"


async def test_a_singleton_decoration_is_built_once() -> None:
    container = _decorated("singleton")

    assert await container.get(Greeter) is await container.get(Greeter)


async def test_a_scoped_decoration_is_shared_within_a_scope_only() -> None:
    container = _decorated("scoped")

    async with container.enter_scope() as first:
        one = await first.get(Greeter)
        assert await first.get(Greeter) is one
    async with container.enter_scope() as second:
        assert await second.get(Greeter) is not one


async def test_a_transient_decoration_is_built_every_time() -> None:
    container = _decorated("transient")

    async with container.enter_scope() as scope:
        first = await scope.get(Greeter)
        second = await scope.get(Greeter)

    assert first is not second
    assert isinstance(first, Loud)
    assert isinstance(second, Loud)
    assert first.inner is not second.inner


async def test_the_inner_generator_is_cleaned_up_on_close() -> None:
    box = _box_type(1)
    container = wireup.create_async_container(
        injectables=[_boxed(plain_resource, box, "singleton"), _decorator(Loud, box, "singleton")]
    )
    greeter = await container.get(Greeter)
    assert isinstance(greeter, Loud)
    inner = greeter.inner
    assert isinstance(inner, Plain)

    await container.close()

    assert inner.closed


async def test_the_inner_is_absent_from_the_collection() -> None:
    box = _box_type(1)
    container = wireup.create_async_container(
        injectables=[
            wireup.instance(Other(), as_type=Greeter, qualifier="other"),
            _boxed(_synthesize_class_factory(Plain), box, "singleton"),
            _decorator(Loud, box, "singleton", qualifier="main"),
        ]
    )

    greeters = await container.get(Sequence[Greeter])

    assert [type(greeter) for greeter in greeters] == [Other, Loud]


async def test_stacked_decorators_wrap_in_order() -> None:
    first_box = _box_type(1)
    second_box = _box_type(2)
    loud = _decorating_factory(_synthesize_class_factory(Loud), "inner", first_box, provides=Loud)
    container = wireup.create_async_container(
        injectables=[
            _boxed(_synthesize_class_factory(Plain), first_box, "singleton"),
            _boxed(loud, second_box, "singleton"),
            _decorator(Exclaiming, second_box, "singleton"),
        ]
    )

    greeter = await container.get(Greeter)

    assert greeter.greet() == "HELLO!"


def test_box_types_are_distinct_and_private() -> None:
    first = _box_type(1)
    second = _box_type(1)

    assert first is not second
    assert first.__module__ == "xtr_dependency_injection.compiler"
    assert first.__name__ == "_Inner_1"
