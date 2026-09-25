"""S1: a synthesized class factory resolves constructor dependencies under the real class."""

from __future__ import annotations

from dataclasses import dataclass
from types import FunctionType
from typing import Annotated, Generic, TypeVar

import pytest
import wireup
from wireup import Inject

from xtr_dependency_injection.compiler.registration import _synthesize_class_factory

pytestmark = pytest.mark.anyio

T = TypeVar("T")


class Dependency:
    pass


class Deferred:
    def __init__(self, dependency: Dependency) -> None:
        self.dependency: Dependency = dependency


class Qualified:
    def __init__(
        self,
        primary: Annotated[Dependency, Inject(qualifier="primary")],
        url: Annotated[str, Inject(config="db.url")],
    ) -> None:
        self.primary: Dependency = primary
        self.url: str = url


@dataclass
class DataclassService:
    dependency: Dependency


class Slotted:
    __slots__: tuple[str, ...] = ("dependency",)

    def __init__(self, dependency: Dependency) -> None:
        self.dependency: Dependency = dependency


class Defaulted:
    def __init__(self, dependency: Dependency, retries=3) -> None:  # noqa: ANN001  # pyright: ignore[reportMissingParameterType]
        self.dependency: Dependency = dependency
        self.retries: int = retries


class KeywordOnly:
    def __init__(self, *, dependency: Dependency) -> None:
        self.dependency: Dependency = dependency


class GenericBase(Generic[T]):
    def __init__(self, dependency: Dependency) -> None:
        self.dependency: Dependency = dependency


class Concrete(GenericBase[int]):
    pass


def _container(*classes: type, config: dict[str, object] | None = None) -> wireup.AsyncContainer:
    return wireup.create_async_container(
        injectables=[
            wireup.instance(Dependency(), as_type=Dependency),
            *(wireup.injectable(_synthesize_class_factory(cls)) for cls in classes),
        ],
        config=config,
    )


async def test_postponed_annotations_resolve_to_the_real_class() -> None:
    container = _container(Deferred)

    built = await container.get(Deferred)

    assert type(built) is Deferred
    assert isinstance(built.dependency, Dependency)


async def test_the_class_itself_stays_unmarked() -> None:
    _ = _container(Deferred)

    assert not hasattr(Deferred, "__wireup_registration__")


async def test_qualifier_and_config_annotations_are_honoured() -> None:
    primary = Dependency()
    container = wireup.create_async_container(
        injectables=[
            wireup.instance(primary, as_type=Dependency, qualifier="primary"),
            wireup.injectable(_synthesize_class_factory(Qualified)),
        ],
        config={"db": {"url": "sqlite://"}},
    )

    built = await container.get(Qualified)

    assert built.primary is primary
    assert built.url == "sqlite://"


async def test_a_dataclass_constructor_is_resolved() -> None:
    built = await _container(DataclassService).get(DataclassService)

    assert isinstance(built.dependency, Dependency)


async def test_a_slotted_class_is_resolved() -> None:
    built = await _container(Slotted).get(Slotted)

    assert isinstance(built.dependency, Dependency)


async def test_an_unannotated_parameter_keeps_its_default() -> None:
    built = await _container(Defaulted).get(Defaulted)

    assert built.retries == 3


async def test_a_keyword_only_parameter_is_resolved() -> None:
    built = await _container(KeywordOnly).get(KeywordOnly)

    assert isinstance(built.dependency, Dependency)


async def test_a_constructor_inherited_from_a_generic_base_is_resolved() -> None:
    built = await _container(Concrete).get(Concrete)

    assert type(built) is Concrete
    assert isinstance(built.dependency, Dependency)


def test_the_factory_is_named_like_the_class() -> None:
    factory = _synthesize_class_factory(Deferred)

    assert isinstance(factory, FunctionType)
    assert factory.__qualname__ == Deferred.__qualname__
    assert factory.__module__ == Deferred.__module__
