from __future__ import annotations

# Read at runtime: the builder keys a factory by its evaluated return type.
from collections.abc import Iterator  # noqa: TC003

import pytest
from wireup.errors import FactoryReturnTypeIsEmptyError

from xtr_dependency_injection.builder import Origin
from xtr_dependency_injection.builder.service_configurator import (
    BuildState,
    Phase,
    ServiceConfigurator,
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


def _state() -> BuildState:
    return BuildState(env="dev", debug=True, bundles=("kernel", "alpha"), configs={})


def _services(state: BuildState | None = None) -> ServiceConfigurator:
    return ServiceConfigurator(state if state is not None else _state(), Origin("bundle", "alpha"))


def test_an_instance_is_keyed_by_its_own_type() -> None:
    state = _state()
    obj = Mailer()

    _ = _services(state).instance(obj, qualifier="main")

    definition = state.store.get((Mailer, "main"))
    assert definition is not None
    assert (definition.provider, definition.kind) == (obj, "instance")
    assert definition.origin == Origin("bundle", "alpha")


def test_set_for_a_factory_is_keyed_by_its_return_type() -> None:
    state = _state()

    _ = _services(state).set(mailer, lifetime="scoped")

    definition = state.store.get((Mailer, None))
    assert definition is not None
    assert (definition.kind, definition.lifetime) == ("factory", "scoped")


def test_a_generator_factory_is_keyed_by_its_yield_type() -> None:
    state = _state()

    _ = _services(state).set(mailer_resource)

    assert state.store.get((Mailer, None)) is not None


def test_a_factory_without_a_return_type_is_refused() -> None:
    with pytest.raises(FactoryReturnTypeIsEmptyError):
        _ = _services().set(untyped)


def test_set_of_something_that_is_not_a_class_or_a_function_is_refused() -> None:
    with pytest.raises(TypeError, match="takes a class or a function"):
        _ = _services().set(Mailer())  # pyright: ignore[reportArgumentType]  # ty: ignore[invalid-argument-type]


def test_set_registers_a_class_under_its_own_type() -> None:
    state = _state()

    _ = _services(state).set(SmtpMailer)

    definition = state.store.get((SmtpMailer, None))
    assert definition is not None
    assert (definition.provider, definition.kind) == (SmtpMailer, "class")


def test_set_for_the_same_key_and_provider_returns_the_existing_definition() -> None:
    state = _state()
    first = _services(state).set(SmtpMailer)

    second = _services(state).set(SmtpMailer)

    assert first is second
    assert len(state.store.entries()) == 1


def test_set_under_another_qualifier_is_added_when_the_class_is_already_defined() -> None:
    state = _state()
    _ = _services(state).set(SmtpMailer)

    _ = _services(state).set(SmtpMailer, qualifier="mw")

    assert state.store.get((SmtpMailer, "mw")) is not None


def test_set_and_alias_share_the_target_key() -> None:
    state = _state()
    _ = _services(state).set(SmtpMailer)

    _services(state).alias(Mailer, SmtpMailer, alias_qualifier="mw")

    assert state.aliases == {(Mailer, "mw"): (SmtpMailer, None)}


def test_load_records_a_late_scan_for_the_bundle() -> None:
    state = _state()

    _services(state).load("pkg.commands")

    assert state.late_scans == [("alpha", ("pkg.commands",))]


@pytest.mark.parametrize("phase", ["autoconfigure", "process"])
def test_load_belongs_to_the_load_phase(phase: Phase) -> None:
    state = _state()
    state.phase = phase

    with pytest.raises(BuilderPhaseError) as caught:
        _services(state).load("pkg")

    assert (caught.value.operation, caught.value.phase) == ("load", phase)


def test_defining_is_allowed_while_autoconfiguring() -> None:
    state = _state()
    state.phase = "autoconfigure"

    _ = _services(state).set(Mailer)

    assert state.store.get((Mailer, None)) is not None


def test_nothing_is_allowed_once_frozen() -> None:
    state = _state()
    state.phase = "frozen"

    with pytest.raises(BuilderFrozenError):
        _ = _services(state).set(Mailer)


def test_a_definition_can_be_tagged_kernel_reset_for_the_compiler_to_wrap() -> None:
    state = _state()

    definition = _services(state).set(mailer).add_tag("kernel.reset", method="clear")

    assert definition.get_tag("kernel.reset") == [{"method": "clear"}]
