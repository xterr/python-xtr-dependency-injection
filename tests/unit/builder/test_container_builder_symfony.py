from __future__ import annotations

import pytest

from xtr_dependency_injection.builder import Definition, Origin
from xtr_dependency_injection.builder.container_builder import ContainerBuilder
from xtr_dependency_injection.builder.service_configurator import BuildState
from xtr_dependency_injection.exception import UnknownServiceError


class Mailer:
    pass


class OtherMailer:
    pass


class Iface:
    pass


def _builder() -> tuple[BuildState, ContainerBuilder]:
    state = BuildState(env="dev", debug=False, bundles=("kernel",), configs={})
    state.phase = "load"
    return state, ContainerBuilder(state, Origin("bundle", "alpha"))


def test_register_adds_a_class_definition_returned_for_mutation() -> None:
    _, builder = _builder()

    definition = builder.register(Mailer)

    assert builder.has_definition(Mailer)
    assert definition.key == (Mailer, None)
    assert definition.kind == "class"


def test_get_definition_reads_a_registered_service() -> None:
    _, builder = _builder()
    _ = builder.register(Mailer)

    assert builder.get_definition(Mailer).provider is Mailer


def test_get_definition_of_an_unknown_key_raises() -> None:
    _, builder = _builder()

    with pytest.raises(UnknownServiceError):
        _ = builder.get_definition(Mailer)


def test_has_definition_ignores_aliases() -> None:
    _, builder = _builder()
    _ = builder.register(Mailer)
    builder.set_alias(Iface, Mailer)

    assert builder.has_definition(Mailer)
    assert not builder.has_definition(Iface)


def test_has_returns_true_for_aliases() -> None:
    _, builder = _builder()
    _ = builder.register(Mailer)
    builder.set_alias(Iface, Mailer)

    assert builder.has(Iface)


def test_find_definition_follows_aliases() -> None:
    _, builder = _builder()
    _ = builder.register(Mailer)
    builder.set_alias(Iface, Mailer)

    assert builder.find_definition(Iface).provider is Mailer


def test_find_definition_missing_target_raises() -> None:
    _, builder = _builder()

    with pytest.raises(UnknownServiceError):
        _ = builder.find_definition(Mailer)


def test_remove_definition_forgets_the_service() -> None:
    _, builder = _builder()
    _ = builder.register(Mailer)

    builder.remove_definition(Mailer)

    assert not builder.has_definition(Mailer)


def test_remove_definition_of_unknown_raises() -> None:
    _, builder = _builder()

    with pytest.raises(UnknownServiceError):
        builder.remove_definition(Mailer)


def test_get_definitions_returns_declaration_order() -> None:
    _, builder = _builder()
    _ = builder.register(Mailer)
    _ = builder.register(OtherMailer)

    assert [d.key[0] for d in builder.get_definitions()] == [Mailer, OtherMailer]


def test_set_definition_swaps_an_existing_definition() -> None:
    state, builder = _builder()
    _ = builder.register(Mailer)
    replacement = Definition(
        key=(Mailer, None),
        provider=OtherMailer,
        kind="class",
        lifetime="singleton",
        origin=Origin("bundle", "alpha"),
    )

    _ = builder.set_definition(replacement)

    assert state.store.get((Mailer, None)) is replacement


def test_get_alias_returns_the_target_key() -> None:
    _, builder = _builder()
    builder.set_alias(Iface, Mailer, target_qualifier="q")

    assert builder.get_alias(Iface) == (Mailer, "q")


def test_get_alias_missing_raises() -> None:
    _, builder = _builder()

    with pytest.raises(UnknownServiceError):
        _ = builder.get_alias(Iface)


def test_remove_alias_forgets_it() -> None:
    _, builder = _builder()
    builder.set_alias(Iface, Mailer)

    builder.remove_alias(Iface)

    assert not builder.has_alias(Iface)


def test_remove_alias_missing_raises() -> None:
    _, builder = _builder()

    with pytest.raises(UnknownServiceError):
        builder.remove_alias(Iface)


def test_find_tagged_service_ids_lists_matching_definitions() -> None:
    _, builder = _builder()
    _ = builder.register(Mailer).add_tag("shipping", role="primary")
    _ = builder.register(OtherMailer).add_tag("shipping", role="backup")

    tagged = builder.find_tagged_service_ids("shipping")

    assert tagged == {
        (Mailer, None): [{"role": "primary"}],
        (OtherMailer, None): [{"role": "backup"}],
    }


def test_set_parameter_reads_back_through_get_parameter() -> None:
    state, _ = _builder()
    state.phase = "build"
    ContainerBuilder(state, Origin("kernel", "kernel")).set_parameter("kernel.env", "dev")

    assert ContainerBuilder(state, Origin("kernel", "kernel")).get_parameter("kernel.env") == "dev"
