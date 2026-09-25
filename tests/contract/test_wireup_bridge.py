"""S5: the bridge reads wireup's marks and keys the way wireup does."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
import wireup

from xtr_dependency_injection.compiler._wireup_bridge import declaration_of, provided_type

pytestmark = pytest.mark.anyio


class Contract:
    pass


@wireup.injectable
class Marked:
    pass


class InheritsTheMark(Marked):
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


def test_a_marked_class_is_declared() -> None:
    declaration = declaration_of(Marked)

    assert declaration is not None
    assert declaration.obj is Marked
    assert declaration.lifetime == "singleton"
    assert declaration.qualifier is None
    assert declaration.as_type is None


def test_every_field_of_the_mark_is_read() -> None:
    declaration = declaration_of(Implementation)

    assert declaration is not None
    assert declaration.as_type is Contract
    assert declaration.qualifier == "q"
    assert declaration.lifetime == "scoped"


def test_a_subclass_inheriting_the_mark_is_not_declared() -> None:
    assert declaration_of(InheritsTheMark) is None


def test_an_unmarked_object_is_not_declared() -> None:
    assert declaration_of(Unmarked) is None
    assert declaration_of(Unmarked()) is None


@pytest.mark.parametrize(
    ("declared", "expected"),
    [(Marked, Marked), (Implementation, Contract), (product, Product), (product_resource, Product)],
)
async def test_the_provided_type_is_the_key_wireup_registers(
    declared: object, expected: type
) -> None:
    declaration = declaration_of(declared)
    assert declaration is not None
    container = wireup.create_async_container(injectables=[declared])

    key = provided_type(declaration)

    assert key is expected
    async with container.enter_scope() as scope:
        assert await scope.get(key, declaration.qualifier) is not None
