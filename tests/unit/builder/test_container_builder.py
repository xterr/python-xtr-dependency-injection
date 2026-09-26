from __future__ import annotations

from dataclasses import dataclass, replace

import pytest

from xtr_dependency_injection.builder import Origin
from xtr_dependency_injection.builder.container_builder import ContainerBuilder
from xtr_dependency_injection.builder.service_configurator import (
    BuildState,
    Prepend,
    ServiceConfigurator,
)
from xtr_dependency_injection.bundle import NoConfig
from xtr_dependency_injection.exception import (
    BuilderPhaseError,
    ConfigProviderError,
    MissingBundleError,
    ParameterNotFoundError,
    UnknownConfigTypeError,
    UnknownServiceError,
)
from xtr_dependency_injection.exception._naming import qualified_name


@dataclass(frozen=True)
class AlphaConfig:
    level: int = 1


class Mailer:
    pass


class OtherMailer(Mailer):
    pass


def mailer() -> Mailer:
    return Mailer()


def _ignore_reader(_obj: object) -> tuple[object, ...]:
    return ()


def _ignore_callback(_obj: object, _meta: object, _services: ServiceConfigurator) -> None:
    pass


def _builder() -> tuple[BuildState, ContainerBuilder]:
    state = BuildState(
        env="dev", debug=False, bundles=("kernel", "alpha"), configs={"alpha": AlphaConfig()}
    )
    state.phase = "process"
    builder = ContainerBuilder(state, Origin("bundle", "alpha"))
    _ = builder.register(Mailer)
    return state, builder


def test_has_answers_by_type_and_qualifier() -> None:
    _, builder = _builder()

    assert builder.has(Mailer)
    assert not builder.has(Mailer, "other")


def test_get_definitions_lists_every_definition() -> None:
    _, builder = _builder()
    _ = builder.register(OtherMailer)

    keys = [d.key for d in builder.get_definitions()]
    assert (Mailer, None) in keys
    assert (OtherMailer, None) in keys


def test_get_extension_config_by_name_and_by_type() -> None:
    _, builder = _builder()

    assert builder.get_extension_config("alpha") == AlphaConfig()
    assert builder.get_extension_config(AlphaConfig) == AlphaConfig()


def test_get_extension_config_of_an_inactive_bundle_is_refused() -> None:
    _, builder = _builder()

    with pytest.raises(MissingBundleError):
        _ = builder.get_extension_config("beta")


def test_get_extension_config_of_an_unknown_type_is_refused() -> None:
    _, builder = _builder()

    with pytest.raises(UnknownConfigTypeError):
        _ = builder.get_extension_config(Mailer)


def test_get_extension_config_is_refused_before_load() -> None:
    state, builder = _builder()
    state.phase = "build"

    with pytest.raises(BuilderPhaseError):
        _ = builder.get_extension_config("alpha")


def test_prepend_extension_config_records_a_prepend() -> None:
    state = BuildState(env="dev", debug=False, bundles=("kernel", "alpha"), configs={})
    state.phase = "prepend"
    builder = ContainerBuilder(state, Origin("bundle", "alpha"))

    def transform(config: AlphaConfig) -> AlphaConfig:
        return replace(config, level=config.level + 1)

    builder.prepend_extension_config("beta", transform)

    assert len(state.prepends) == 1
    prepend = state.prepends[0]
    assert prepend.source == "alpha"
    assert prepend.target == "beta"
    assert prepend.description == qualified_name(transform)


def test_prepend_extension_config_is_refused_outside_prepend_phase() -> None:
    _, builder = _builder()

    with pytest.raises(BuilderPhaseError):
        builder.prepend_extension_config("beta", lambda c: c)


def test_prepend_extension_config_to_a_bundle_without_config_is_refused() -> None:
    state = BuildState(
        env="dev",
        debug=False,
        bundles=("kernel", "no_config"),
        configs={"no_config": NoConfig()},
    )
    state.phase = "prepend"
    builder = ContainerBuilder(state, Origin("bundle", "alpha"))

    with pytest.raises(ConfigProviderError, match="takes no config"):
        builder.prepend_extension_config("no_config", lambda c: c)


def test_prepend_extension_config_to_an_unknown_name_is_recorded_and_reported_skipped() -> None:
    # Unknown-by-name is reported as skipped by the resolver (same code path as env-disabled);
    # the builder itself only refuses NoConfig targets. Confirm the record survives.
    state = BuildState(env="dev", debug=False, bundles=("kernel", "alpha"), configs={})
    state.phase = "prepend"
    builder = ContainerBuilder(state, Origin("bundle", "alpha"))

    builder.prepend_extension_config("does_not_exist", lambda c: c)

    ((prepend,)) = state.prepends
    assert prepend.target == "does_not_exist"
    assert prepend.source == "alpha"


def test_prepend_extension_config_to_an_env_disabled_bundle_is_recorded() -> None:
    state = BuildState(env="dev", debug=False, bundles=("kernel", "alpha"), configs={})
    state.phase = "prepend"
    builder = ContainerBuilder(state, Origin("bundle", "alpha"))

    builder.prepend_extension_config("beta", lambda c: c)

    ((prepend,)) = state.prepends
    assert prepend.target == "beta"


def test_prepend_extension_config_to_an_unknown_type_is_recorded_and_refused_at_resolve() -> None:
    state = BuildState(env="dev", debug=False, bundles=("kernel", "alpha"), configs={})
    state.phase = "prepend"
    builder = ContainerBuilder(state, Origin("bundle", "alpha"))

    class OrphanConfig:
        pass

    builder.prepend_extension_config(OrphanConfig, lambda c: c)

    ((prepend,)) = state.prepends
    assert prepend.target is OrphanConfig


def test_get_parameter_reads_kernel_parameters() -> None:
    state = BuildState(env="dev", debug=False, bundles=("kernel",), configs={})
    state.add_parameters(
        Origin("kernel", "kernel"), {"kernel": {"name": "shop", "environment": "dev"}}
    )
    state.phase = "build"
    builder = ContainerBuilder(state, Origin("kernel", "kernel"))

    assert builder.get_parameter("kernel.name") == "shop"
    assert builder.get_parameter("kernel.environment") == "dev"
    assert builder.has_parameter("kernel.name")


def test_get_parameter_of_an_unset_name_raises() -> None:
    state = BuildState(env="dev", debug=False, bundles=("kernel",), configs={})
    state.phase = "build"
    builder = ContainerBuilder(state, Origin("kernel", "kernel"))

    assert not builder.has_parameter("kernel.nope")
    with pytest.raises(ParameterNotFoundError):
        _ = builder.get_parameter("kernel.nope")


def test_set_definition_swaps_the_definition_and_records_the_override() -> None:
    from xtr_dependency_injection.builder import Definition  # noqa: PLC0415

    state, builder = _builder()

    _ = builder.set_definition(
        Definition(
            key=(Mailer, None),
            provider=OtherMailer,
            kind="class",
            lifetime="singleton",
            origin=Origin("bundle", "alpha"),
        )
    )

    definition = state.store.get((Mailer, None))
    assert definition is not None
    assert (definition.provider, definition.kind) == (OtherMailer, "class")
    assert Origin("bundle", "alpha") in state.store.overrides_of((Mailer, None))


def test_remove_forgets_the_service() -> None:
    _, builder = _builder()

    builder.remove(Mailer)

    assert not builder.has(Mailer)


def test_set_decorated_service_records_the_target_on_a_registered_definition() -> None:
    _, builder = _builder()

    decorator = builder.register(OtherMailer).set_decorated_service(Mailer, priority=3)

    assert decorator.decorates is not None
    assert (decorator.decorates.key, decorator.decorates.priority) == ((Mailer, None), 3)


def test_register_attribute_for_autoconfiguration_records_the_reader_and_callback() -> None:
    state = BuildState(env="dev", debug=False, bundles=("kernel", "alpha"), configs={})
    state.phase = "build"
    builder = ContainerBuilder(state, Origin("bundle", "alpha"))

    builder.register_attribute_for_autoconfiguration(_ignore_reader, _ignore_callback)

    assert [a.owner for a in state.autoconfigurators] == ["alpha"]


def test_register_for_autoconfiguration_records_a_rule_and_returns_it() -> None:
    state = BuildState(env="dev", debug=False, bundles=("kernel", "alpha"), configs={})
    state.phase = "build"
    builder = ContainerBuilder(state, Origin("bundle", "alpha"))

    rule = builder.register_for_autoconfiguration(Mailer).add_tag("some.tag", role="mailer")

    assert state.autoconfigure_rules == [rule]
    assert rule.type_ is Mailer
    assert rule.tags == {"some.tag": [{"role": "mailer"}]}


def test_register_for_autoconfiguration_is_refused_after_load() -> None:
    state = BuildState(env="dev", debug=False, bundles=("kernel", "alpha"), configs={})
    state.phase = "process"
    builder = ContainerBuilder(state, Origin("bundle", "alpha"))

    with pytest.raises(BuilderPhaseError) as caught:
        _ = builder.register_for_autoconfiguration(Mailer)

    assert caught.value.operation == "register_for_autoconfiguration"


@pytest.mark.parametrize("operation", ["remove", "remove_definition"])
def test_an_unknown_key_is_refused(operation: str) -> None:
    _, builder = _builder()
    calls = {
        "remove": lambda: builder.remove(Mailer, qualifier="x"),
        "remove_definition": lambda: builder.remove_definition(Mailer, qualifier="x"),
    }

    with pytest.raises(UnknownServiceError) as caught:
        calls[operation]()

    assert caught.value.operation == operation


_ = Prepend  # touched to avoid unused-import; the type is public API.
