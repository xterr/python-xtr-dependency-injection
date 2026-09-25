from __future__ import annotations

import pytest

from xtr_dependency_injection.builder import Origin
from xtr_dependency_injection.builder.autoconfigurator import (
    Apply,
    Autoconfigurator,
    run_autoconfigurators,
)
from xtr_dependency_injection.builder.service_configurator import BuildState, ServiceConfigurator
from xtr_dependency_injection.scan.scanned_object import ScannedObject


class Tagged:
    tags: tuple[str, ...] = ("a", "b")


class Untagged:
    pass


def _tags(obj: object) -> tuple[str, ...]:
    return tuple(getattr(obj, "tags", ()))


def _ignore(_obj: object, _meta: object, _services: ServiceConfigurator) -> None:
    pass


def _candidates() -> list[ScannedObject]:
    return [
        ScannedObject(Tagged, "tests:Tagged", None, 1),
        ScannedObject(Untagged, "tests:Untagged", None, 2),
    ]


def test_apply_runs_once_per_metadata_item_of_matching_candidates() -> None:
    applied: list[tuple[object, object]] = []
    state = BuildState(env="dev", debug=False, bundles=("alpha",), configs={})

    def record(obj: object, meta: object, _services: ServiceConfigurator) -> None:
        applied.append((obj, meta))

    run_autoconfigurators(
        [Autoconfigurator("alpha", _tags, record)],
        _candidates(),
        lambda owner, _candidate: ServiceConfigurator(state, Origin("bundle", owner)),
    )

    assert applied == [(Tagged, "a"), (Tagged, "b")]


def test_autoconfigurators_are_the_outer_loop() -> None:
    seen: list[str] = []
    state = BuildState(env="dev", debug=False, bundles=("alpha", "beta"), configs={})

    def everything(obj: object) -> tuple[object]:
        return (obj,)

    def seen_by(owner: str) -> Apply:
        def record(obj: object, _meta: object, _services: ServiceConfigurator) -> None:
            seen.append(f"{owner} {obj}")

        return record

    run_autoconfigurators(
        [
            Autoconfigurator("alpha", everything, seen_by("alpha")),
            Autoconfigurator("beta", everything, seen_by("beta")),
        ],
        _candidates(),
        lambda owner, _candidate: ServiceConfigurator(state, Origin("bundle", owner)),
    )

    assert [entry.split()[0] for entry in seen] == ["alpha", "alpha", "beta", "beta"]


def test_the_configurator_names_the_candidate() -> None:
    requested: list[tuple[str, str]] = []
    state = BuildState(env="dev", debug=False, bundles=("alpha",), configs={})

    def configurator_for(owner: str, candidate: ScannedObject) -> ServiceConfigurator:
        requested.append((owner, candidate.name))
        return ServiceConfigurator(state, Origin("bundle", owner))

    run_autoconfigurators(
        [Autoconfigurator("alpha", _tags, _ignore)], _candidates(), configurator_for
    )

    assert requested == [("alpha", "tests:Tagged")]


def test_a_failing_reader_propagates_with_a_note() -> None:
    def broken(_obj: object) -> tuple[object, ...]:
        raise RuntimeError("bug")

    state = BuildState(env="dev", debug=False, bundles=("alpha",), configs={})

    with pytest.raises(RuntimeError, match="bug") as caught:
        run_autoconfigurators(
            [Autoconfigurator("alpha", broken, _ignore)],
            _candidates(),
            lambda owner, _c: ServiceConfigurator(state, Origin("bundle", owner)),
        )

    assert "of bundle alpha on tests:Tagged" in caught.value.__notes__[0]
