from __future__ import annotations

from typing import Protocol

import pytest

from xtr_dependency_injection.builder import Origin
from xtr_dependency_injection.builder.container_builder import ContainerBuilder
from xtr_dependency_injection.builder.service_configurator import BuildState, ServiceConfigurator
from xtr_dependency_injection.compiler.check_alias_validity_pass import CheckAliasValidityPass
from xtr_dependency_injection.exception import InvalidDefinitionError


class Mailer:
    pass


class SmtpMailer(Mailer):
    pass


class Unrelated:
    pass


class Sender(Protocol):
    def send(self) -> None: ...


def _state() -> BuildState:
    state = BuildState(env="dev", debug=False, bundles=("kernel",), configs={})
    state.phase = "process"
    return state


def _process(state: BuildState) -> None:
    CheckAliasValidityPass().process(ContainerBuilder(state, Origin("kernel", "kernel")))


def test_an_alias_to_a_class_implementing_it_is_valid() -> None:
    state = _state()
    services = ServiceConfigurator(state, Origin("app", "tests"))
    _ = services.set(SmtpMailer)
    services.alias(Mailer, SmtpMailer)

    _process(state)


def test_an_alias_to_a_class_not_implementing_it_is_refused() -> None:
    state = _state()
    services = ServiceConfigurator(state, Origin("app", "tests"))
    _ = services.set(Unrelated)
    services.alias(Mailer, Unrelated)

    with pytest.raises(InvalidDefinitionError, match="does not implement"):
        _process(state)


def test_an_alias_to_a_missing_target_is_left_to_a_later_pass() -> None:
    state = _state()
    ServiceConfigurator(state, Origin("app", "tests")).alias(Mailer, Unrelated)

    _process(state)


def test_a_protocol_that_cannot_be_checked_at_runtime_is_skipped() -> None:
    state = _state()
    services = ServiceConfigurator(state, Origin("app", "tests"))
    _ = services.set(Unrelated)
    services.alias(Sender, Unrelated)

    _process(state)
