from __future__ import annotations

from typing import TYPE_CHECKING, Literal

import pytest

from xtr_dependency_injection.builder import Definition, Origin
from xtr_dependency_injection.builder.container_builder import ContainerBuilder
from xtr_dependency_injection.builder.service_configurator import BuildState
from xtr_dependency_injection.compiler.check_definition_validity_pass import (
    CheckDefinitionValidityPass,
)
from xtr_dependency_injection.config import env
from xtr_dependency_injection.exception import InvalidDefinitionError

if TYPE_CHECKING:
    from xtr_dependency_injection.builder.definition import Lifetime


class Mailer:
    pass


class SmtpMailer(Mailer):
    pass


class Unrelated:
    pass


def mailer() -> Mailer:
    return SmtpMailer()


def unannotated():  # noqa: ANN201 — the missing annotation is what is tested.
    return SmtpMailer()


def _process(
    provider: object,
    kind: Literal["class", "factory", "instance"],
    *,
    key: type = Mailer,
    lifetime: Lifetime = "singleton",
) -> None:
    state = BuildState(env="dev", debug=False, bundles=("kernel",), configs={})
    state.store.add(Definition((key, None), provider, kind, lifetime, Origin("app", "tests")))
    state.phase = "process"
    CheckDefinitionValidityPass().process(ContainerBuilder(state, Origin("kernel", "kernel")))


@pytest.mark.parametrize(
    ("provider", "kind"),
    [(SmtpMailer, "class"), (mailer, "factory"), (SmtpMailer(), "instance")],
    ids=["class", "factory", "instance"],
)
def test_a_consistent_definition_is_valid(
    provider: object, kind: Literal["class", "factory", "instance"]
) -> None:
    _process(provider, kind)


@pytest.mark.parametrize(
    ("provider", "kind", "reason"),
    [
        (mailer, "class", "needs a class"),
        (Unrelated, "class", "is not a"),
        (SmtpMailer, "factory", "needs a function"),
        (unannotated, "factory", "no return annotation"),
        (Unrelated(), "instance", "is not a"),
    ],
    ids=["class-not-a-class", "class-wrong-type", "factory-a-class", "factory-bare", "instance"],
)
def test_an_inconsistent_definition_is_refused(
    provider: object, kind: Literal["class", "factory", "instance"], reason: str
) -> None:
    with pytest.raises(InvalidDefinitionError, match=reason):
        _process(provider, kind)


def test_an_instance_is_always_a_singleton() -> None:
    with pytest.raises(InvalidDefinitionError, match="always a singleton"):
        _process(SmtpMailer(), "instance", lifetime="scoped")


def test_an_unknown_lifetime_is_refused() -> None:
    with pytest.raises(InvalidDefinitionError, match="unknown lifetime"):
        _process(SmtpMailer, "class", lifetime="forever")  # pyright: ignore[reportArgumentType]  # ty: ignore[invalid-argument-type] — an invalid lifetime is what is tested.


class Configured(Mailer):
    def __init__(self, host: str, /, port: int = 25, *, user: str = "") -> None:
        self.host: str = host
        self.port: int = port
        self.user: str = user


def open_ended(**options: object) -> Mailer:
    del options
    return SmtpMailer()


def _process_arguments(
    provider: object, kind: Literal["class", "factory", "instance"], arguments: dict[str, object]
) -> None:
    state = BuildState(env="dev", debug=False, bundles=("kernel",), configs={})
    definition = Definition((Mailer, None), provider, kind, "singleton", Origin("app", "tests"))
    state.store.add(definition.set_arguments(arguments))
    state.phase = "process"
    CheckDefinitionValidityPass().process(ContainerBuilder(state, Origin("kernel", "kernel")))


def test_arguments_naming_keyword_parameters_are_valid() -> None:
    _process_arguments(Configured, "class", {"port": 2525, "user": "u"})
    _process_arguments(open_ended, "factory", {"anything": 1})


@pytest.mark.parametrize(
    ("provider", "kind", "arguments", "reason"),
    [
        (Configured, "class", {"hostname": "x"}, "names no parameter"),
        (Configured, "class", {"host": "x"}, "cannot be passed by keyword"),
        (mailer, "factory", {"host": "x"}, "names no parameter"),
        (SmtpMailer(), "instance", {"host": "x"}, "takes no arguments"),
    ],
    ids=["unknown", "positional-only", "factory-unknown", "instance"],
)
def test_arguments_that_do_not_fit_the_provider_are_refused(
    provider: object,
    kind: Literal["class", "factory", "instance"],
    arguments: dict[str, object],
    reason: str,
) -> None:
    with pytest.raises(InvalidDefinitionError, match=reason):
        _process_arguments(provider, kind, arguments)


class Holder:
    def __init__(self, host: object) -> None:
        self.host: object = host


def _factories() -> tuple[object, object, object]:
    host = env("MAIL_HOST")
    holder = Holder(host)
    config = {"host": host}

    def read_host() -> object:
        return host

    def through_a_function() -> Mailer:
        _ = read_host
        return SmtpMailer()

    def through_an_object() -> Mailer:
        _ = holder
        return SmtpMailer()

    def through_a_mapping() -> Mailer:
        _ = config
        return SmtpMailer()

    return through_a_function, through_an_object, through_a_mapping


@pytest.mark.parametrize(
    ("index", "holder"),
    [(0, "the function"), (1, "the Holder object")],
    ids=["function", "object"],
)
def test_a_factory_reaching_a_placeholder_it_cannot_resolve_is_refused(
    index: int, holder: str
) -> None:
    factory = _factories()[index]

    with pytest.raises(InvalidDefinitionError, match=f"{holder}.*set_argument"):
        _process(factory, "factory")


def test_a_factory_closing_over_a_mapping_of_placeholders_is_valid() -> None:
    _process(_factories()[2], "factory")
