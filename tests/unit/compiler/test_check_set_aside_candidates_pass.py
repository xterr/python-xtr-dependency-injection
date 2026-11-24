from __future__ import annotations

import pytest

from xtr_dependency_injection.builder import Origin
from xtr_dependency_injection.builder.autoconfigurator import Autoconfigurator
from xtr_dependency_injection.builder.container_builder import ContainerBuilder
from xtr_dependency_injection.builder.service_configurator import BuildState, ServiceConfigurator
from xtr_dependency_injection.compiler.check_set_aside_candidates_pass import (
    CheckSetAsideCandidatesPass,
)
from xtr_dependency_injection.diagnostics import SetAsideReport
from xtr_dependency_injection.exception import SetAsideModuleUsedError
from xtr_dependency_injection.scan.scanned_object import ScannedObject


class Claimed:
    claimed: bool = True


class Unclaimed:
    pass


def _claimed(obj: object) -> tuple[object, ...]:
    return (obj,) if getattr(obj, "claimed", False) else ()


def _ignore(_obj: object, _meta: object, _services: ServiceConfigurator) -> None:
    pass


def _state(*objects: type, reader: Autoconfigurator | None = None) -> BuildState:
    state = BuildState(env="prod", debug=False, bundles=("kernel", "alpha"), configs={})
    state.phase = "process"
    if reader is not None:
        state.autoconfigurators.append(reader)
    state.set_aside.extend(
        ScannedObject(obj, f"app.seed:{obj.__qualname__}", None, order)
        for order, obj in enumerate(objects, start=1)
    )
    state.set_aside_modules["app.seed"] = SetAsideReport("app.seed", ("faker",), "app.base")
    return state


def _process(state: BuildState) -> None:
    CheckSetAsideCandidatesPass().process(ContainerBuilder(state, Origin("kernel", "kernel")))


def test_nothing_set_aside_is_nothing_to_refuse() -> None:
    _process(_state(reader=Autoconfigurator("alpha", _claimed, _ignore)))


def test_a_set_aside_object_no_reader_claims_is_let_be() -> None:
    _process(_state(Unclaimed, reader=Autoconfigurator("alpha", _claimed, _ignore)))


def test_a_set_aside_object_a_reader_claims_fails_the_build() -> None:
    state = _state(Unclaimed, Claimed, reader=Autoconfigurator("alpha", _claimed, _ignore))

    with pytest.raises(SetAsideModuleUsedError) as caught:
        _process(state)

    error = caught.value
    assert (error.name, error.use, error.module, error.missing, error.through) == (
        "app.seed:Claimed",
        "bundle 'alpha' would register it",
        "app.seed",
        ("faker",),
        "app.base",
    )


def test_a_reader_failing_on_a_set_aside_object_says_so() -> None:
    def failing(obj: object) -> tuple[object, ...]:
        del obj
        raise LookupError

    with pytest.raises(LookupError) as caught:
        _process(_state(Unclaimed, reader=Autoconfigurator("alpha", failing, _ignore)))

    (note,) = caught.value.__notes__
    assert "of bundle alpha on app.seed:Unclaimed, defined in a module set aside" in note
