"""Todo 18: ``@as_decorator`` / ``set_decorated_service`` with ``OnInvalid`` + lifetime."""

from __future__ import annotations

from typing import Annotated

import pytest

from xtr_dependency_injection.builder.container_builder import ContainerBuilder
from xtr_dependency_injection.builder.definition import Origin
from xtr_dependency_injection.builder.service_configurator import (
    BuildState,
    ServiceConfigurator,
)
from xtr_dependency_injection.compiler.decorator_service_pass import resolve_decorations_pass
from xtr_dependency_injection.decorator.as_decorator import (
    AutowireDecorated,
    OnInvalid,
)
from xtr_dependency_injection.exception import (
    DecoratorSignatureError,
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
    return BuildState(env="dev", debug=False, bundles=("kernel",), configs={})


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
        resolve_decorations_pass(_builder(state), [])


def test_missing_target_with_ignore_drops_the_decorator() -> None:
    state = _state()
    _ = (
        ServiceConfigurator(state, Origin("app", "tests:StrictBus"))
        .set(StrictBus)
        .set_decorated_service(Bus, on_invalid=OnInvalid.IGNORE)
    )

    resolve_decorations_pass(_builder(state), [])

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

    resolve_decorations_pass(_builder(state), [])

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
        resolve_decorations_pass(_builder(state), [])


def test_decorator_inherits_targets_lifetime_and_leaves_only_under_target_key() -> None:
    state = _state()
    _ = ServiceConfigurator(state, Origin("bundle", "beta")).set(Bus, lifetime="transient")
    _ = (
        ServiceConfigurator(state, Origin("app", "tests:StrictBus"))
        .set(StrictBus, lifetime="singleton")
        .set_decorated_service(Bus)
    )

    resolve_decorations_pass(_builder(state), [])

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

    resolve_decorations_pass(_builder(state), [])

    ordered = state.decorations[(Bus, None)]
    assert [d.decorator for d in ordered] == [HighPrio, LowPrio]
