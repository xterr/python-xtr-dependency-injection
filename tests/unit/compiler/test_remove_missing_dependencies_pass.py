from __future__ import annotations

from xtr_dependency_injection.builder import Origin
from xtr_dependency_injection.builder.container_builder import ContainerBuilder
from xtr_dependency_injection.builder.service_configurator import BuildState, ServiceConfigurator
from xtr_dependency_injection.compiler.remove_missing_dependencies_pass import (
    remove_if_missing_pass,
)
from xtr_dependency_injection.decorator.remove_if_missing import REMOVE_IF_MISSING_TAG


class Alpha:
    pass


class Beta:
    pass


class Peer:
    pass


def _state(*bundles: str) -> BuildState:
    return BuildState(env="dev", debug=False, bundles=("kernel", *bundles), configs={})


def test_remove_if_missing_by_service_drops_when_the_service_is_absent() -> None:
    state = _state()
    _ = (
        ServiceConfigurator(state, Origin("app", "tests:Alpha"))
        .set(Alpha)
        .add_tag(REMOVE_IF_MISSING_TAG, service=Peer)
    )

    remove_if_missing_pass(ContainerBuilder(state, Origin("kernel", "kernel")))

    assert state.store.get((Alpha, None)) is None


def test_remove_if_missing_by_service_keeps_when_the_service_is_present() -> None:
    state = _state()
    _ = ServiceConfigurator(state, Origin("app", "tests:Peer")).set(Peer)
    _ = (
        ServiceConfigurator(state, Origin("app", "tests:Alpha"))
        .set(Alpha)
        .add_tag(REMOVE_IF_MISSING_TAG, service=Peer)
    )

    remove_if_missing_pass(ContainerBuilder(state, Origin("kernel", "kernel")))

    assert state.store.get((Alpha, None)) is not None


def test_remove_if_missing_by_class_path_drops_on_missing_module() -> None:
    state = _state()
    _ = (
        ServiceConfigurator(state, Origin("app", "tests:Alpha"))
        .set(Alpha)
        .add_tag(REMOVE_IF_MISSING_TAG, class_="no_such_module_xyz_15:Missing")
    )

    remove_if_missing_pass(ContainerBuilder(state, Origin("kernel", "kernel")))

    assert state.store.get((Alpha, None)) is None


def test_remove_if_missing_by_class_path_keeps_on_existing_class() -> None:
    state = _state()
    _ = (
        ServiceConfigurator(state, Origin("app", "tests:Alpha"))
        .set(Alpha)
        .add_tag(
            REMOVE_IF_MISSING_TAG,
            class_="xtr_dependency_injection.kernel.kernel:Kernel",
        )
    )

    remove_if_missing_pass(ContainerBuilder(state, Origin("kernel", "kernel")))

    assert state.store.get((Alpha, None)) is not None


def test_remove_if_missing_by_package_drops_on_missing_distribution() -> None:
    state = _state()
    _ = (
        ServiceConfigurator(state, Origin("app", "tests:Alpha"))
        .set(Alpha)
        .add_tag(
            REMOVE_IF_MISSING_TAG,
            class_="xtr_dependency_injection.kernel.kernel:Kernel",
            package="no-such-dist-xyz-15",
        )
    )

    remove_if_missing_pass(ContainerBuilder(state, Origin("kernel", "kernel")))

    assert state.store.get((Alpha, None)) is None


def test_remove_if_missing_removes_aliases_pointing_at_the_dropped_definition() -> None:
    state = _state()
    services = ServiceConfigurator(state, Origin("app", "tests:Alpha"))
    _ = services.set(Alpha).add_tag(REMOVE_IF_MISSING_TAG, service=Peer)
    services.alias(Beta, Alpha)

    remove_if_missing_pass(ContainerBuilder(state, Origin("kernel", "kernel")))

    assert (Beta, None) not in state.aliases


def test_remove_if_missing_sweeps_until_it_settles() -> None:
    state = _state()
    _ = (
        ServiceConfigurator(state, Origin("app", "tests:Alpha"))
        .set(Alpha)
        .add_tag(REMOVE_IF_MISSING_TAG, service=Peer)
    )
    # Beta requires Alpha; Alpha is dropped, which then makes Beta drop.
    _ = (
        ServiceConfigurator(state, Origin("app", "tests:Beta"))
        .set(Beta)
        .add_tag(REMOVE_IF_MISSING_TAG, service=Alpha)
    )

    remove_if_missing_pass(ContainerBuilder(state, Origin("kernel", "kernel")))

    assert state.store.get((Alpha, None)) is None
    assert state.store.get((Beta, None)) is None


def test_remove_if_missing_is_a_noop_without_any_tag() -> None:
    state = _state()
    _ = ServiceConfigurator(state, Origin("app", "tests:Alpha")).set(Alpha)

    remove_if_missing_pass(ContainerBuilder(state, Origin("kernel", "kernel")))

    assert state.store.get((Alpha, None)) is not None
