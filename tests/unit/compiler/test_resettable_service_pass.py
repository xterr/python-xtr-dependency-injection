from __future__ import annotations

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


def test_a_tag_without_a_method_is_refused() -> None:
    state = _state()
    _ = ServiceConfigurator(state, Origin("app", "tests")).set(Cache).add_tag(RESET_TAG)

    with pytest.raises(InvalidDefinitionError, match='"method" attribute'):
        _process(state)
