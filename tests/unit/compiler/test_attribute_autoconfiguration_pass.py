from __future__ import annotations

import pytest

from xtr_dependency_injection.builder import Origin
from xtr_dependency_injection.builder.autoconfigurator import Apply, Autoconfigurator
from xtr_dependency_injection.builder.container_builder import ContainerBuilder
from xtr_dependency_injection.builder.service_configurator import BuildState, ServiceConfigurator
from xtr_dependency_injection.compiler.attribute_autoconfiguration_pass import (
    AttributeAutoconfigurationPass,
)
from xtr_dependency_injection.scan.scanned_object import ScannedObject


class Tagged:
    tags: tuple[str, ...] = ("a", "b")


class Untagged:
    pass


def _tags(obj: object) -> tuple[str, ...]:
    return tuple(getattr(obj, "tags", ()))


def _ignore(_obj: object, _meta: object, _services: ServiceConfigurator) -> None:
    pass


def _state(*autoconfigurators: Autoconfigurator) -> BuildState:
    state = BuildState(env="dev", debug=False, bundles=("kernel", "alpha", "beta"), configs={})
    state.phase = "process"
    state.autoconfigurators.extend(autoconfigurators)
    state.candidates.extend(
        [
            ScannedObject(Tagged, "tests:Tagged", None, 1),
            ScannedObject(Untagged, "tests:Untagged", None, 2),
        ]
    )
    return state


def _process(state: BuildState) -> None:
    AttributeAutoconfigurationPass().process(ContainerBuilder(state, Origin("kernel", "kernel")))


def test_apply_runs_once_per_metadata_item_of_matching_candidates() -> None:
    applied: list[tuple[object, object]] = []

    def record(obj: object, meta: object, _services: ServiceConfigurator) -> None:
        applied.append((obj, meta))

    _process(_state(Autoconfigurator("alpha", _tags, record)))

    assert applied == [(Tagged, "a"), (Tagged, "b")]


def test_autoconfigurators_are_the_outer_loop() -> None:
    seen: list[str] = []

    def everything(obj: object) -> tuple[object]:
        return (obj,)

    def seen_by(owner: str) -> Apply:
        def record(obj: object, _meta: object, _services: ServiceConfigurator) -> None:
            seen.append(f"{owner} {obj}")

        return record

    _process(
        _state(
            Autoconfigurator("alpha", everything, seen_by("alpha")),
            Autoconfigurator("beta", everything, seen_by("beta")),
        )
    )

    assert [entry.split()[0] for entry in seen] == ["alpha", "alpha", "beta", "beta"]


def test_what_apply_defines_carries_the_bundle_and_the_candidate() -> None:
    def register(obj: object, _meta: object, services: ServiceConfigurator) -> None:
        if isinstance(obj, type):
            _ = services.set(obj)

    state = _state(Autoconfigurator("alpha", _tags, register))

    _process(state)

    definition = state.store.get((Tagged, None))
    assert definition is not None
    assert definition.origin == Origin("bundle", "alpha", "via autoconfigure of tests:Tagged")


def test_a_failing_reader_propagates_with_a_note() -> None:
    def broken(_obj: object) -> tuple[object, ...]:
        raise RuntimeError("bug")

    with pytest.raises(RuntimeError, match="bug") as caught:
        _process(_state(Autoconfigurator("alpha", broken, _ignore)))

    assert "of bundle alpha on tests:Tagged" in caught.value.__notes__[0]
