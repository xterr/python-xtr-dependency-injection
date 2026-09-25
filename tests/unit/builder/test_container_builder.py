from __future__ import annotations

from dataclasses import dataclass

import pytest

from xtr_dependency_injection.builder import Origin
from xtr_dependency_injection.builder.container_builder import ContainerBuilder
from xtr_dependency_injection.builder.service_configurator import BuildState, DecorationRequest
from xtr_dependency_injection.exception import (
    BuilderPhaseError,
    MissingBundleError,
    UnknownConfigTypeError,
    UnknownServiceError,
)


@dataclass(frozen=True)
class AlphaConfig:
    level: int = 1


class Mailer:
    pass


class OtherMailer(Mailer):
    pass


def _builder() -> tuple[BuildState, ContainerBuilder]:
    state = BuildState(
        env="dev", debug=False, bundles=("kernel", "alpha"), configs={"alpha": AlphaConfig()}
    )
    state.phase = "process"
    builder = ContainerBuilder(state, Origin("bundle", "alpha"))
    builder.service(Mailer)
    return state, builder


def test_has_answers_by_type_and_qualifier() -> None:
    _, builder = _builder()

    assert builder.has(Mailer)
    assert not builder.has(Mailer, "other")


def test_definitions_filter_by_type() -> None:
    _, builder = _builder()
    builder.instance(1)

    assert [d.key for d in builder.definitions(Mailer)] == [(Mailer, None)]
    assert len(builder.definitions()) == 2


def test_config_of_by_name_and_by_type() -> None:
    _, builder = _builder()

    assert builder.config_of("alpha") == AlphaConfig()
    assert builder.config_of(AlphaConfig) == AlphaConfig()


def test_config_of_an_inactive_bundle_is_refused() -> None:
    _, builder = _builder()

    with pytest.raises(MissingBundleError):
        _ = builder.config_of("beta")


def test_config_of_an_unknown_type_is_refused() -> None:
    _, builder = _builder()

    with pytest.raises(UnknownConfigTypeError):
        _ = builder.config_of(Mailer)


def test_replace_swaps_the_provider_keeping_the_lifetime() -> None:
    state, builder = _builder()

    builder.replace(Mailer, OtherMailer)

    definition = state.store.get((Mailer, None))
    assert definition is not None
    assert (definition.provider, definition.kind, definition.lifetime) == (
        OtherMailer,
        "class",
        "singleton",
    )


def test_remove_forgets_the_service() -> None:
    _, builder = _builder()

    builder.remove(Mailer)

    assert not builder.has(Mailer)


def test_decorate_records_a_request() -> None:
    state, builder = _builder()

    builder.decorate(Mailer, OtherMailer, priority=3)

    assert state.decorations == [
        DecorationRequest((Mailer, None), OtherMailer, 3, f"{__name__}:OtherMailer", 0)
    ]


@pytest.mark.parametrize("operation", ["replace", "remove", "decorate"])
def test_an_unknown_key_is_refused(operation: str) -> None:
    _, builder = _builder()
    calls = {
        "replace": lambda: builder.replace(Mailer, OtherMailer, qualifier="x"),
        "remove": lambda: builder.remove(Mailer, qualifier="x"),
        "decorate": lambda: builder.decorate(Mailer, OtherMailer, qualifier="x"),
    }

    with pytest.raises(UnknownServiceError) as caught:
        calls[operation]()

    assert caught.value.operation == operation


def test_scan_is_refused_while_processing() -> None:
    _, builder = _builder()

    with pytest.raises(BuilderPhaseError):
        builder.scan("pkg")
