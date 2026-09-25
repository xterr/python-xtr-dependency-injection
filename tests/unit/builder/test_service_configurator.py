from __future__ import annotations

# Read at runtime: the builder keys a factory by its evaluated return type.
from collections.abc import Iterator  # noqa: TC003

import pytest
from wireup.errors import FactoryReturnTypeIsEmptyError

from xtr_dependency_injection.builder import Origin
from xtr_dependency_injection.builder.service_configurator import (
    BuildState,
    Phase,
    ResettableRequest,
    ServiceConfigurator,
    kind_of,
)
from xtr_dependency_injection.exception import BuilderFrozenError, BuilderPhaseError


class Mailer:
    pass


class SmtpMailer(Mailer):
    pass


def mailer() -> Mailer:
    return Mailer()


def mailer_resource() -> Iterator[Mailer]:
    yield Mailer()


def untyped():  # noqa: ANN201
    return Mailer()


def _ignore(_obj: object, _meta: object, _services: ServiceConfigurator) -> None:
    pass


def _state() -> BuildState:
    return BuildState(env="dev", debug=True, bundles=("kernel", "alpha"), configs={})


def _services(state: BuildState | None = None) -> ServiceConfigurator:
    return ServiceConfigurator(state if state is not None else _state(), Origin("bundle", "alpha"))


def test_env_debug_and_active_bundles_are_exposed() -> None:
    services = _services()

    assert (services.env, services.debug) == ("dev", True)
    assert services.has_bundle("alpha")
    assert not services.has_bundle("beta")


def test_an_instance_is_keyed_by_its_own_type() -> None:
    state = _state()
    obj = Mailer()

    _services(state).instance(obj, qualifier="main", priority=2)

    definition = state.store.get((Mailer, "main"))
    assert definition is not None
    assert (definition.provider, definition.kind, definition.priority) == (obj, "instance", 2)
    assert definition.origin == Origin("bundle", "alpha")


def test_an_instance_may_be_keyed_by_as_type() -> None:
    state = _state()

    _services(state).instance(SmtpMailer(), as_type=Mailer)

    assert state.store.get((Mailer, None)) is not None


def test_a_factory_is_keyed_by_its_return_type() -> None:
    state = _state()

    _services(state).factory(mailer, lifetime="scoped")

    definition = state.store.get((Mailer, None))
    assert definition is not None
    assert (definition.kind, definition.lifetime) == ("factory", "scoped")


def test_a_generator_factory_is_keyed_by_its_yield_type() -> None:
    state = _state()

    _services(state).factory(mailer_resource)

    assert state.store.get((Mailer, None)) is not None


def test_a_factory_without_a_return_type_is_refused() -> None:
    with pytest.raises(FactoryReturnTypeIsEmptyError):
        _services().factory(untyped)


def test_a_factory_must_be_a_function() -> None:
    with pytest.raises(TypeError, match="takes a function"):
        _services().factory(Mailer)


def test_a_service_is_keyed_by_its_class() -> None:
    state = _state()

    _services(state).service(SmtpMailer, as_type=Mailer)

    definition = state.store.get((Mailer, None))
    assert definition is not None
    assert (definition.provider, definition.kind) == (SmtpMailer, "class")


def test_a_service_already_provided_by_the_same_class_is_a_no_op() -> None:
    state = _state()
    _services(state).service(Mailer)

    _services(state).service(Mailer, qualifier="again")

    assert state.store.get((Mailer, "again")) is None


def test_scan_records_a_late_scan_for_the_bundle() -> None:
    state = _state()

    _services(state).scan("pkg.commands")

    assert state.late_scans == [("alpha", ("pkg.commands",))]


def test_autoconfigure_records_the_bundle() -> None:
    state = _state()

    _services(state).autoconfigure(lambda _obj: (), _ignore)

    assert [a.owner for a in state.autoconfigurators] == ["alpha"]


def test_parameters_are_recorded_with_their_source() -> None:
    state = _state()

    _services(state).parameters({"x": 1})

    assert state.parameters == [("bundle alpha", {"x": 1})]


def test_resettable_records_a_request() -> None:
    state = _state()

    _services(state).resettable(Mailer, method="clear")

    assert state.resettables == [ResettableRequest((Mailer, None), "clear")]


@pytest.mark.parametrize("phase", ["autoconfigure", "process"])
def test_scan_belongs_to_the_load_phase(phase: Phase) -> None:
    state = _state()
    state.phase = phase

    with pytest.raises(BuilderPhaseError) as caught:
        _services(state).scan("pkg")

    assert (caught.value.operation, caught.value.phase) == ("scan", phase)


def test_autoconfigure_belongs_to_the_load_phase() -> None:
    state = _state()
    state.phase = "process"

    with pytest.raises(BuilderPhaseError):
        _services(state).autoconfigure(lambda _obj: (), _ignore)


def test_defining_is_allowed_while_autoconfiguring() -> None:
    state = _state()
    state.phase = "autoconfigure"

    _services(state).service(Mailer)

    assert state.store.get((Mailer, None)) is not None


def test_nothing_is_allowed_once_frozen() -> None:
    state = _state()
    state.phase = "frozen"

    with pytest.raises(BuilderFrozenError):
        _services(state).service(Mailer)


def test_kind_of_judges_the_provider() -> None:
    assert kind_of(Mailer) == "class"
    assert kind_of(mailer) == "factory"
    assert kind_of(Mailer()) == "instance"
