from __future__ import annotations

import pytest

from xtr_dependency_injection.builder import Origin
from xtr_dependency_injection.builder.container_builder import ContainerBuilder
from xtr_dependency_injection.builder.service_configurator import BuildState, ServiceConfigurator
from xtr_dependency_injection.compiler.resolve_references_to_aliases_pass import (
    ResolveReferencesToAliasesPass,
)
from xtr_dependency_injection.exception import ServiceCircularReferenceError


class Alpha:
    pass


class Beta:
    pass


class Gamma:
    pass


def _state() -> BuildState:
    state = BuildState(env="dev", debug=False, bundles=("kernel",), configs={})
    state.phase = "process"
    return state


def _process(state: BuildState) -> None:
    ResolveReferencesToAliasesPass().process(ContainerBuilder(state, Origin("kernel", "kernel")))


def test_an_alias_chain_points_straight_at_its_definition() -> None:
    state = _state()
    services = ServiceConfigurator(state, Origin("app", "tests"))
    _ = services.set(Gamma)
    services.alias(Alpha, Beta)
    services.alias(Beta, Gamma)

    _process(state)

    assert state.aliases == {(Alpha, None): (Gamma, None), (Beta, None): (Gamma, None)}
    assert state.alias_origins[(Alpha, None)] == Origin("app", "tests")


def test_a_looping_alias_chain_is_refused_with_its_path() -> None:
    state = _state()
    services = ServiceConfigurator(state, Origin("app", "tests"))
    services.alias(Alpha, Beta)
    services.alias(Beta, Alpha)

    with pytest.raises(ServiceCircularReferenceError) as caught:
        _process(state)

    assert caught.value.path == ((Alpha, None), (Beta, None), (Alpha, None))
