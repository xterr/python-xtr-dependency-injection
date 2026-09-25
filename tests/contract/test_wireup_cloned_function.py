"""S2: a cloned factory keeps its kind, its cleanup, and leaves the original unmarked."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Iterator

import pytest
import wireup

from xtr_dependency_injection.compiler.registration import _clone_function

pytestmark = pytest.mark.anyio


class Resource:
    def __init__(self) -> None:
        self.closed: bool = False


def sync_resource() -> Resource:
    return Resource()


async def coroutine_resource() -> Resource:
    return Resource()


def generator_resource() -> Iterator[Resource]:
    resource = Resource()
    yield resource
    resource.closed = True


async def async_generator_resource() -> AsyncIterator[Resource]:
    resource = Resource()
    yield resource
    resource.closed = True


@pytest.mark.parametrize(
    "factory",
    [sync_resource, coroutine_resource, generator_resource, async_generator_resource],
)
async def test_a_clone_of_every_kind_builds_the_resource(factory: Callable[..., object]) -> None:
    container = wireup.create_async_container(
        injectables=[wireup.injectable(_clone_function(factory))]
    )

    assert isinstance(await container.get(Resource), Resource)


@pytest.mark.parametrize("factory", [generator_resource, async_generator_resource])
async def test_a_cloned_generator_is_cleaned_up_on_close(factory: Callable[..., object]) -> None:
    container = wireup.create_async_container(
        injectables=[wireup.injectable(_clone_function(factory))]
    )
    resource = await container.get(Resource)

    await container.close()

    assert resource.closed


@pytest.mark.parametrize(
    "factory",
    [sync_resource, coroutine_resource, generator_resource, async_generator_resource],
)
def test_the_original_stays_unmarked(factory: Callable[..., object]) -> None:
    _ = wireup.injectable(_clone_function(factory))

    assert not hasattr(factory, "__wireup_registration__")
