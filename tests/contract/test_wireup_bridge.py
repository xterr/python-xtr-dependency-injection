"""S5: the bridge keys the way wireup does and answers is_registered without side effects.

These tests pin wireup's own behaviour, so they use ``wireup.injectable``
directly — this file is one of the two contract modules that intentionally
keep the wireup marker.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest
import wireup
from wireup import AsyncContainer

from xtr_dependency_injection.compiler._wireup_bridge import is_registered, key_type

pytestmark = pytest.mark.anyio


class Contract:
    pass


@wireup.injectable
class Marked:
    pass


@wireup.injectable(as_type=Contract, qualifier="q", lifetime="scoped")
class Implementation(Contract):
    pass


class Product:
    pass


@wireup.injectable
def product() -> Product:
    return Product()


@wireup.injectable
def product_resource() -> Iterator[Product]:
    yield Product()


class Unmarked:
    pass


@pytest.mark.parametrize(
    ("provider", "as_type", "qualifier", "expected"),
    [
        (Marked, None, None, Marked),
        (Implementation, Contract, "q", Contract),
        (product, None, None, Product),
        (product_resource, None, None, Product),
    ],
)
async def test_the_key_type_is_what_wireup_registers(
    provider: Callable[..., object] | type,
    as_type: type | None,
    qualifier: str | None,
    expected: type,
) -> None:
    container = wireup.create_async_container(injectables=[provider])

    key = key_type(provider, as_type)

    assert key is expected
    async with container.enter_scope() as scope:
        assert await scope.get(key, qualifier) is not None


async def test_is_registered_answers_by_type_and_qualifier() -> None:
    container = wireup.create_async_container(injectables=[Marked, Implementation])

    assert is_registered(container, Marked, None)
    assert is_registered(container, Contract, "q")
    assert not is_registered(container, Contract, None)
    assert not is_registered(container, Unmarked, None)


async def test_is_registered_finds_wireups_self_registered_container() -> None:
    container = wireup.create_async_container()

    assert is_registered(container, AsyncContainer, None)
