"""S6: ``_map_result`` maps each built value once, lazily, keeping cleanup."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Iterator
from types import FunctionType
from typing import Literal

import pytest
import wireup

from xtr_dependency_injection.compiler.registration import _clone_function, _map_result

pytestmark = pytest.mark.anyio


class Resource:
    def __init__(self) -> None:
        self.closed: bool = False
        self.error: BaseException | None = None


def sync_resource() -> Resource:
    return Resource()


async def coroutine_resource() -> Resource:
    return Resource()


def generator_resource() -> Iterator[Resource]:
    resource = Resource()
    try:
        yield resource
    except ValueError as error:
        resource.error = error
        raise
    finally:
        resource.closed = True


async def async_generator_resource() -> AsyncIterator[Resource]:
    resource = Resource()
    try:
        yield resource
    except ValueError as error:
        resource.error = error
        raise
    finally:
        resource.closed = True


Lifetime = Literal["singleton", "scoped", "transient"]


class Other:
    pass


ALL_KINDS = [sync_resource, coroutine_resource, generator_resource, async_generator_resource]
GENERATORS = [generator_resource, async_generator_resource]


def _counting(seen: list[Resource]) -> Callable[[Resource], Resource]:
    def record(value: Resource) -> Resource:
        seen.append(value)
        return value

    return record


def _mapped(
    factory: Callable[..., object], seen: list[Resource], lifetime: Lifetime = "singleton"
) -> Callable[..., object]:
    mapped = _map_result(_clone_function(factory), _counting(seen), provides=Resource)
    return wireup.injectable(mapped, lifetime=lifetime)


@pytest.mark.parametrize("factory", ALL_KINDS)
async def test_the_mapper_runs_once_per_built_singleton(factory: Callable[..., object]) -> None:
    seen: list[Resource] = []
    container = wireup.create_async_container(injectables=[_mapped(factory, seen)])

    first = await container.get(Resource)
    second = await container.get(Resource)

    assert first is second
    assert seen == [first]


@pytest.mark.parametrize("factory", ALL_KINDS)
async def test_the_mapper_runs_once_per_transient_build(factory: Callable[..., object]) -> None:
    seen: list[Resource] = []
    container = wireup.create_async_container(injectables=[_mapped(factory, seen, "transient")])

    async with container.enter_scope() as scope:
        first = await scope.get(Resource)
        second = await scope.get(Resource)

    assert seen == [first, second]


@pytest.mark.parametrize("factory", ALL_KINDS)
async def test_the_mapper_never_runs_for_an_unbuilt_service(factory: Callable[..., object]) -> None:
    seen: list[Resource] = []
    container = wireup.create_async_container(
        injectables=[_mapped(factory, seen), wireup.instance(Other(), as_type=Other)]
    )

    _ = await container.get(Other)

    assert seen == []


@pytest.mark.parametrize("factory", GENERATORS)
async def test_a_mapped_singleton_generator_is_cleaned_up_on_close(
    factory: Callable[..., object],
) -> None:
    container = wireup.create_async_container(injectables=[_mapped(factory, [])])
    resource = await container.get(Resource)

    await container.close()

    assert resource.closed


@pytest.mark.parametrize("factory", GENERATORS)
async def test_a_scope_error_is_thrown_into_the_inner_generator(
    factory: Callable[..., object],
) -> None:
    container = wireup.create_async_container(injectables=[_mapped(factory, [], "scoped")])
    built: list[Resource] = []

    async def fail_inside_a_scope() -> None:
        async with container.enter_scope() as scope:
            built.append(await scope.get(Resource))
            raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        await fail_inside_a_scope()

    assert built[0].closed
    assert isinstance(built[0].error, ValueError)


def test_the_mapped_factory_is_named_like_the_original() -> None:
    mapped = _map_result(sync_resource, _counting([]), provides=Resource)

    assert isinstance(mapped, FunctionType)
    assert mapped.__qualname__ == sync_resource.__qualname__
