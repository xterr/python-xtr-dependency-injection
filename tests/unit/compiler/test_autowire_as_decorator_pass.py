from __future__ import annotations

from typing import Annotated

from xtr_dependency_injection.builder import Origin
from xtr_dependency_injection.builder.container_builder import ContainerBuilder
from xtr_dependency_injection.builder.definition import Decorates
from xtr_dependency_injection.builder.service_configurator import BuildState
from xtr_dependency_injection.compiler.autowire_as_decorator_pass import AutowireAsDecoratorPass
from xtr_dependency_injection.decorator.as_decorator import (
    AutowireDecorated,
    OnInvalid,
    as_decorator,
)
from xtr_dependency_injection.scan.scanned_object import ScannedObject


class Bus:
    pass


@as_decorator(Bus, priority=3, on_invalid=OnInvalid.IGNORE)
class TracingBus(Bus):
    def __init__(self, inner: Annotated[Bus, AutowireDecorated()]) -> None:
        self.inner: Bus = inner


@as_decorator(Bus, qualifier="audit")
def auditing_bus(inner: Annotated[Bus, AutowireDecorated()]) -> Bus:
    return inner


def _process(*scanned: ScannedObject) -> BuildState:
    state = BuildState(env="dev", debug=False, bundles=("kernel", "beta"), configs={})
    state.phase = "process"
    state.scanned_decorators.extend(scanned)
    AutowireAsDecoratorPass().process(ContainerBuilder(state, Origin("kernel", "kernel")))
    return state


def test_a_scanned_class_decorator_becomes_a_decorating_definition() -> None:
    state = _process(ScannedObject(TracingBus, "tests:TracingBus", None, 1))

    (definition,) = state.store.entries()
    assert definition.key == (TracingBus, ".decorator.tests:TracingBus")
    assert definition.kind == "class"
    assert definition.decorates == Decorates((Bus, None), 3, OnInvalid.IGNORE)
    assert definition.origin == Origin("app", "tests:TracingBus")


def test_a_scanned_factory_decorator_does_not_claim_the_decorated_key() -> None:
    state = _process(ScannedObject(auditing_bus, "tests:auditing_bus", "beta", 1))

    (definition,) = state.store.entries()
    assert definition.key == (Bus, ".decorator.tests:auditing_bus")
    assert definition.kind == "factory"
    assert definition.decorates == Decorates((Bus, "audit"))
    assert definition.origin == Origin("bundle", "beta", "decorator tests:auditing_bus")
