from __future__ import annotations

import pytest

from xtr_dependency_injection.builder import Origin
from xtr_dependency_injection.builder.container_builder import ContainerBuilder
from xtr_dependency_injection.builder.service_configurator import BuildState, ServiceConfigurator
from xtr_dependency_injection.compiler.remove_missing_dependencies_pass import (
    RemoveMissingDependenciesPass,
)
from xtr_dependency_injection.decorator.remove_if_missing import REMOVE_IF_MISSING_TAG
from xtr_dependency_injection.exception import InvalidDefinitionError


class Alpha:
    pass


class Beta:
    pass


class Peer:
    pass


def _state() -> BuildState:
    state = BuildState(env="dev", debug=False, bundles=("kernel",), configs={})
    state.phase = "process"
    return state


def _tagged(state: BuildState, defined: type, **condition: object) -> ServiceConfigurator:
    services = ServiceConfigurator(state, Origin("app", f"tests:{defined.__name__}"))
    _ = services.set(defined).add_tag(REMOVE_IF_MISSING_TAG, **condition)
    return services


def _process(state: BuildState) -> None:
    RemoveMissingDependenciesPass().process(ContainerBuilder(state, Origin("kernel", "kernel")))


def test_a_missing_service_drops_the_definition() -> None:
    state = _state()
    _ = _tagged(state, Alpha, service=Peer)

    _process(state)

    assert state.store.get((Alpha, None)) is None


def test_a_present_service_keeps_the_definition() -> None:
    state = _state()
    _ = ServiceConfigurator(state, Origin("app", "tests:Peer")).set(Peer)
    _ = _tagged(state, Alpha, service=Peer)

    _process(state)

    assert state.store.get((Alpha, None)) is not None


def test_a_service_reached_through_an_alias_keeps_the_definition() -> None:
    state = _state()
    services = ServiceConfigurator(state, Origin("app", "tests:Peer"))
    _ = services.set(Peer)
    services.alias(Beta, Peer)
    _ = _tagged(state, Alpha, service=Beta)

    _process(state)

    assert state.store.get((Alpha, None)) is not None


def test_a_missing_module_drops_the_definition() -> None:
    state = _state()
    _ = _tagged(state, Alpha, class_="no_such_module_xyz_15:Missing")

    _process(state)

    assert state.store.get((Alpha, None)) is None


def test_an_existing_class_keeps_the_definition() -> None:
    state = _state()
    _ = _tagged(state, Alpha, class_="xtr_dependency_injection.kernel.kernel:Kernel")

    _process(state)

    assert state.store.get((Alpha, None)) is not None


def test_a_missing_distribution_drops_the_definition() -> None:
    state = _state()
    _ = _tagged(
        state,
        Alpha,
        class_="xtr_dependency_injection.kernel.kernel:Kernel",
        package="no-such-dist-xyz-15",
    )

    _process(state)

    assert state.store.get((Alpha, None)) is None


def test_the_aliases_of_a_dropped_definition_are_dropped_too() -> None:
    state = _state()
    _tagged(state, Alpha, service=Peer).alias(Beta, Alpha)

    _process(state)

    assert (Beta, None) not in state.aliases


def test_the_sweep_repeats_until_it_settles() -> None:
    state = _state()
    _ = _tagged(state, Alpha, service=Peer)
    # Beta requires Alpha; Alpha is dropped, which then makes Beta drop.
    _ = _tagged(state, Beta, service=Alpha)

    _process(state)

    assert state.store.get((Alpha, None)) is None
    assert state.store.get((Beta, None)) is None


def test_every_removal_is_logged_with_its_reason() -> None:
    state = _state()
    _tagged(state, Alpha, package="no-such-dist-xyz-15").alias(Beta, Alpha)

    _process(state)

    log = state.compiler.get_log()
    assert len(log) == 2
    assert log[0].endswith("package no-such-dist-xyz-15 is missing.")
    assert "it aliases" in log[1]


def test_an_unknown_attribute_is_refused() -> None:
    state = _state()
    _ = _tagged(state, Alpha, parent_packages="x")

    with pytest.raises(InvalidDefinitionError, match="'parent_packages'"):
        _process(state)


def test_a_tag_without_any_condition_is_refused() -> None:
    state = _state()
    _ = _tagged(state, Alpha)

    with pytest.raises(InvalidDefinitionError, match="needs one of"):
        _process(state)


def test_it_does_nothing_without_any_tag() -> None:
    state = _state()
    _ = ServiceConfigurator(state, Origin("app", "tests:Alpha")).set(Alpha)

    _process(state)

    assert state.store.get((Alpha, None)) is not None
