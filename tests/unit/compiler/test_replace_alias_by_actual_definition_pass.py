from __future__ import annotations

import pytest

from xtr_dependency_injection.builder import Origin
from xtr_dependency_injection.builder.container_builder import ContainerBuilder
from xtr_dependency_injection.builder.service_configurator import BuildState, ServiceConfigurator
from xtr_dependency_injection.compiler.replace_alias_by_actual_definition_pass import (
    ReplaceAliasByActualDefinitionPass,
)
from xtr_dependency_injection.exception import UnknownServiceError


class Alpha:
    pass


class Peer:
    pass


def _state() -> BuildState:
    state = BuildState(env="dev", debug=False, bundles=("kernel",), configs={})
    state.phase = "process"
    return state


def _process(state: BuildState) -> None:
    ReplaceAliasByActualDefinitionPass().process(
        ContainerBuilder(state, Origin("kernel", "kernel"))
    )


def test_an_alias_becomes_a_forwarding_definition_with_the_targets_lifetime() -> None:
    state = _state()
    services = ServiceConfigurator(state, Origin("bundle", "beta"))
    _ = services.set(Peer, lifetime="scoped")
    services.alias(Alpha, Peer)

    _process(state)

    forwarding = state.store.get((Alpha, None))
    assert forwarding is not None
    assert forwarding.kind == "factory"
    assert forwarding.lifetime == "scoped"
    assert forwarding.origin == Origin("bundle", "beta", "alias")
    assert state.aliases == {(Alpha, None): (Peer, None)}


def test_an_alias_to_a_missing_target_is_refused() -> None:
    state = _state()
    ServiceConfigurator(state, Origin("app", "tests:Alpha")).alias(Alpha, Peer)

    with pytest.raises(UnknownServiceError, match="set_alias"):
        _process(state)


def test_a_forwarding_definition_is_recorded_against_its_target() -> None:
    state = _state()
    services = ServiceConfigurator(state, Origin("bundle", "beta"))
    _ = services.set(Peer)
    services.alias(Alpha, Peer, alias_qualifier="a")

    _process(state)

    assert state.forwards == {(Alpha, "a"): (Peer, None)}


def test_an_alias_with_a_definition_of_its_own_is_not_a_forward() -> None:
    state = _state()
    services = ServiceConfigurator(state, Origin("bundle", "beta"))
    _ = services.set(Peer)
    _ = services.set(Alpha)
    services.alias(Alpha, Peer)

    _process(state)

    assert state.forwards == {}
