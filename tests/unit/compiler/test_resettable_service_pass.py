from __future__ import annotations

from typing import final

import pytest

from xtr_dependency_injection.builder import Origin
from xtr_dependency_injection.builder.container_builder import ContainerBuilder
from xtr_dependency_injection.builder.service_configurator import BuildState, ServiceConfigurator
from xtr_dependency_injection.compiler.resettable_service_pass import (
    RESET_TAG,
    ResettableServicePass,
)
from xtr_dependency_injection.exception import InvalidDefinitionError


class Cache:
    def clear(self) -> None:
        pass


def cache() -> Cache:
    return Cache()


def optional_cache() -> Cache | None:
    return Cache()


def _state() -> BuildState:
    state = BuildState(env="dev", debug=False, bundles=("kernel",), configs={})
    state.phase = "process"
    return state


def _process(state: BuildState) -> None:
    ResettableServicePass().process(ContainerBuilder(state, Origin("kernel", "kernel")))


def test_a_tag_naming_an_existing_method_is_valid() -> None:
    state = _state()
    _ = (
        ServiceConfigurator(state, Origin("app", "tests"))
        .set(Cache)
        .add_tag(RESET_TAG, method="clear")
    )

    _process(state)


def test_a_factory_is_checked_against_the_type_it_returns() -> None:
    state = _state()
    _ = (
        ServiceConfigurator(state, Origin("app", "tests"))
        .set(cache)
        .add_tag(RESET_TAG, method="flush")
    )

    with pytest.raises(InvalidDefinitionError, match="'flush'"):
        _process(state)


@final
class SlottedCache:
    __slots__ = ("entries",)

    def __init__(self) -> None:
        self.entries: list[str] = []

    def clear(self) -> None:
        self.entries.clear()


@final
class WeakSlottedCache:
    # The interpreter fills __weakref__ itself; there is nothing to initialise.
    __slots__ = (
        # The interpreter fills it.
        "__weakref__",  # pyright: ignore[reportUninitializedInstanceVariable]
        "entries",
    )

    def __init__(self) -> None:
        self.entries: list[str] = []

    def clear(self) -> None:
        self.entries.clear()


@pytest.mark.parametrize("lifetime", ["scoped", "transient"])
def test_a_short_lived_class_without_weak_references_is_refused(lifetime: str) -> None:
    state = _state()
    _ = (
        ServiceConfigurator(state, Origin("app", "tests"))
        # The wrong type is the case under test.
        .set(SlottedCache, lifetime=lifetime)  # pyright: ignore[reportArgumentType]  # ty: ignore[invalid-argument-type]
        .add_tag(RESET_TAG, method="clear")
    )

    with pytest.raises(InvalidDefinitionError, match="__weakref__"):
        _process(state)


def test_a_singleton_without_weak_references_is_valid() -> None:
    state = _state()
    _ = (
        ServiceConfigurator(state, Origin("app", "tests"))
        .set(SlottedCache)
        .add_tag(RESET_TAG, method="clear")
    )

    _process(state)


def test_a_short_lived_class_with_weak_references_is_valid() -> None:
    state = _state()
    _ = (
        ServiceConfigurator(state, Origin("app", "tests"))
        .set(WeakSlottedCache, lifetime="transient")
        .add_tag(RESET_TAG, method="clear")
    )

    _process(state)


def test_a_factory_returning_an_optional_is_checked_against_its_non_none_member() -> None:
    state = _state()
    _ = (
        ServiceConfigurator(state, Origin("app", "tests"))
        .set(optional_cache)
        .add_tag(RESET_TAG, method="clear")
    )

    _process(state)


def test_a_tag_without_a_method_is_refused() -> None:
    state = _state()
    _ = ServiceConfigurator(state, Origin("app", "tests")).set(Cache).add_tag(RESET_TAG)

    with pytest.raises(InvalidDefinitionError, match='"method" attribute'):
        _process(state)
