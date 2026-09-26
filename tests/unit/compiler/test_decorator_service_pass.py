from __future__ import annotations

from typing import Annotated

import pytest

from xtr_dependency_injection.builder.container_builder import ContainerBuilder
from xtr_dependency_injection.builder.definition import Origin
from xtr_dependency_injection.builder.service_configurator import (
    BuildState,
    ServiceConfigurator,
)
from xtr_dependency_injection.compiler.decorator_service_pass import DecoratorServicePass
from xtr_dependency_injection.decorator.as_decorator import (
    AutowireDecorated,
    OnInvalid,
)
from xtr_dependency_injection.exception import (
    DecoratorSignatureError,
    InvalidDefinitionError,
    UnknownServiceError,
)


class Bus:
    pass


class NullableBus:
    def __init__(self, inner: Annotated[Bus | None, AutowireDecorated()]) -> None:
        self.inner: Bus | None = inner


class StrictBus:
    def __init__(self, inner: Annotated[Bus, AutowireDecorated()]) -> None:
        self.inner: Bus = inner


def _state() -> BuildState:
    state = BuildState(env="dev", debug=False, bundles=("kernel",), configs={})
    state.phase = "process"
    return state


def _builder(state: BuildState) -> ContainerBuilder:
    return ContainerBuilder(state, Origin("kernel", "kernel"))


def test_missing_target_with_exception_raises() -> None:
    state = _state()
    _ = (
        ServiceConfigurator(state, Origin("app", "tests:StrictBus"))
        .set(StrictBus)
        .set_decorated_service(Bus)
    )

    with pytest.raises(UnknownServiceError, match="cannot decorate"):
        DecoratorServicePass().process(_builder(state))


def test_missing_target_with_ignore_drops_the_decorator() -> None:
    state = _state()
    _ = (
        ServiceConfigurator(state, Origin("app", "tests:StrictBus"))
        .set(StrictBus)
        .set_decorated_service(Bus, on_invalid=OnInvalid.IGNORE)
    )

    DecoratorServicePass().process(_builder(state))

    assert state.store.get((StrictBus, None)) is None
    assert state.store.get((Bus, None)) is None
    assert state.decorations == {}


def test_missing_target_with_null_registers_decorator_under_target_key() -> None:
    state = _state()
    _ = (
        ServiceConfigurator(state, Origin("app", "tests:NullableBus"))
        .set(NullableBus)
        .set_decorated_service(Bus, on_invalid=OnInvalid.NULL)
    )

    DecoratorServicePass().process(_builder(state))

    assert state.store.get((NullableBus, None)) is None
    fallback = state.store.get((Bus, None))
    assert fallback is not None
    assert fallback.kind == "factory"
    assert state.decorations == {}


def test_missing_target_with_null_requires_none_in_annotation() -> None:
    state = _state()
    _ = (
        ServiceConfigurator(state, Origin("app", "tests:StrictBus"))
        .set(StrictBus)
        .set_decorated_service(Bus, on_invalid=OnInvalid.NULL)
    )

    with pytest.raises(DecoratorSignatureError, match="allow None"):
        DecoratorServicePass().process(_builder(state))


def test_decorator_inherits_targets_lifetime_and_leaves_only_under_target_key() -> None:
    state = _state()
    _ = ServiceConfigurator(state, Origin("bundle", "beta")).set(Bus, lifetime="transient")
    _ = (
        ServiceConfigurator(state, Origin("app", "tests:StrictBus"))
        .set(StrictBus, lifetime="singleton")
        .set_decorated_service(Bus)
    )

    DecoratorServicePass().process(_builder(state))

    assert state.store.get((StrictBus, None)) is None
    (decoration,) = state.decorations[(Bus, None)]
    assert decoration.inner_parameter == "inner"


def test_multiple_decorators_stack_by_priority_descending() -> None:
    state = _state()
    _ = ServiceConfigurator(state, Origin("bundle", "beta")).set(Bus)

    class HighPrio:
        def __init__(self, inner: Annotated[Bus, AutowireDecorated()]) -> None:
            self.inner: Bus = inner

    class LowPrio:
        def __init__(self, inner: Annotated[Bus, AutowireDecorated()]) -> None:
            self.inner: Bus = inner

    _ = (
        ServiceConfigurator(state, Origin("app", "tests:LowPrio"))
        .set(LowPrio)
        .set_decorated_service(Bus, priority=1)
    )
    _ = (
        ServiceConfigurator(state, Origin("app", "tests:HighPrio"))
        .set(HighPrio)
        .set_decorated_service(Bus, priority=10)
    )

    DecoratorServicePass().process(_builder(state))

    ordered = state.decorations[(Bus, None)]
    assert [d.decorator for d in ordered] == [HighPrio, LowPrio]


def test_an_ignored_decorator_is_logged() -> None:
    state = _state()
    _ = (
        ServiceConfigurator(state, Origin("app", "tests:StrictBus"))
        .set(StrictBus)
        .set_decorated_service(Bus, on_invalid=OnInvalid.IGNORE)
    )

    DecoratorServicePass().process(_builder(state))

    (entry,) = state.compiler.get_log()
    assert "StrictBus" in entry
    assert entry.endswith("is missing.")


class LabelledBus:
    def __init__(self, inner: Annotated[Bus, AutowireDecorated()], label: str) -> None:
        self.inner: Bus = inner
        self.label: str = label


def test_a_decorators_arguments_travel_with_its_decoration() -> None:
    state = _state()
    _ = ServiceConfigurator(state, Origin("app", "tests:Bus")).set(Bus)
    _ = (
        ServiceConfigurator(state, Origin("app", "tests:LabelledBus"))
        .set(LabelledBus)
        .set_decorated_service(Bus)
        .set_argument("label", "outer")
    )

    DecoratorServicePass().process(_builder(state))

    (decoration,) = state.decorations[Bus, None]
    assert decoration.arguments == {"label": "outer"}


@pytest.mark.parametrize(
    ("name", "reason"), [("inner", "the decorated service"), ("nope", "names no parameter")]
)
def test_a_decorator_argument_that_does_not_fit_is_refused(name: str, reason: str) -> None:
    state = _state()
    _ = ServiceConfigurator(state, Origin("app", "tests:Bus")).set(Bus)
    _ = (
        ServiceConfigurator(state, Origin("app", "tests:LabelledBus"))
        .set(LabelledBus)
        .set_decorated_service(Bus)
        .set_argument(name, "x")
    )

    with pytest.raises(InvalidDefinitionError, match=reason):
        DecoratorServicePass().process(_builder(state))
