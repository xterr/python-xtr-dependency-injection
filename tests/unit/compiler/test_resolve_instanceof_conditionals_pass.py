from __future__ import annotations

from xtr_dependency_injection.builder import Origin
from xtr_dependency_injection.builder.container_builder import ContainerBuilder
from xtr_dependency_injection.builder.service_configurator import BuildState, ServiceConfigurator
from xtr_dependency_injection.compiler.resolve_instanceof_conditionals_pass import (
    ResolveInstanceofConditionalsPass,
)


class Base:
    pass


class GivenOne(Base):
    pass


class LeftToDefault(Base):
    pass


def _scoped_rule_for_base() -> BuildState:
    state = BuildState(env="dev", debug=False, bundles=("kernel",), configs={})
    state.phase = "build"
    rule = ContainerBuilder(state, Origin("bundle", "alpha")).register_for_autoconfiguration(Base)
    rule.lifetime = "scoped"
    state.phase = "load"
    return state


def _process(state: BuildState) -> None:
    state.phase = "process"
    ResolveInstanceofConditionalsPass().process(ContainerBuilder(state, Origin("kernel", "kernel")))


def test_a_rule_sets_the_lifetime_of_a_service_given_none() -> None:
    state = _scoped_rule_for_base()
    definition = ServiceConfigurator(state, Origin("app", "tests")).set(LeftToDefault)

    _process(state)

    assert definition.lifetime == "scoped"


def test_a_rule_never_overrides_a_lifetime_given_explicitly() -> None:
    state = _scoped_rule_for_base()
    services = ServiceConfigurator(state, Origin("app", "tests"))
    definition = services.set(GivenOne, lifetime="singleton")

    _process(state)

    assert definition.lifetime == "singleton"
