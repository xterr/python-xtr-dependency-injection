"""The compiler against a real wireup container: kinds, order, reset, decoration, errors."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from typing import Literal

import pytest
import wireup
from typing_extensions import override
from wireup.errors import WireupError

from xtr_dependency_injection.builder import Definition, Origin, ServiceKey
from xtr_dependency_injection.compiler.wireup_compiler import (
    Decoration,
    compile_container,
    emission_order,
    emit_injectables,
)
from xtr_dependency_injection.decorator.as_decorator import Inner

pytestmark = pytest.mark.anyio

KERNEL = Origin("kernel", "kernel")
ALPHA = Origin("bundle", "alpha")
BETA = Origin("bundle", "beta")
APP = Origin("app", "app:x")


class Plugin:
    def name(self) -> str:
        return type(self).__name__


class First(Plugin):
    pass


class Second(Plugin):
    pass


class Third(Plugin):
    pass


class Buffer:
    def reset(self) -> None:
        pass


class Loud(Plugin):
    def __init__(self, inner: Inner[Plugin]) -> None:
        self.inner: Plugin = inner

    @override
    def name(self) -> str:
        return f"Loud({self.inner.name()})"


class Missing:
    pass


class NeedsMissing:
    def __init__(self, missing: Missing) -> None:
        self.missing: Missing = missing


@wireup.injectable
class Declared:
    pass


def third() -> Third:
    return Third()


def buffer_resource() -> Iterator[Buffer]:
    yield Buffer()


Kind = Literal["class", "factory", "instance", "declared"]


def _definition(  # noqa: PLR0913 — mirrors Definition's fields.
    provided: type,
    provider: object,
    origin: Origin = ALPHA,
    *,
    qualifier: str | None = None,
    priority: int = 0,
    kind: Kind = "class",
) -> Definition:
    return Definition((provided, qualifier), provider, kind, "singleton", origin, priority)


def _compile(
    *definitions: Definition,
    decorations: Mapping[ServiceKey, Sequence[Decoration]] | None = None,
    tracked: list[tuple[object, str]] | None = None,
) -> wireup.AsyncContainer:
    sink = tracked if tracked is not None else []
    injectables = emit_injectables(
        definitions, decorations or {}, lambda instance, method: sink.append((instance, method))
    )
    return compile_container(
        injectables, definitions, parameters={}, concurrent_scoped_access=False
    )


def test_emission_order_is_kernel_bundles_then_app_by_priority() -> None:
    app = _definition(Plugin, First, APP, qualifier="app")
    beta = _definition(Plugin, Second, BETA, qualifier="beta")
    alpha_low = _definition(Plugin, Third, ALPHA, qualifier="alpha_low")
    alpha_high = _definition(Plugin, Third, ALPHA, qualifier="alpha_high", priority=5)
    kernel = _definition(Plugin, First, KERNEL, qualifier="kernel")

    ordered = emission_order(
        [app, beta, alpha_low, alpha_high, kernel], ["kernel", "alpha", "beta"]
    )

    assert [d.key[1] for d in ordered] == ["kernel", "alpha_high", "alpha_low", "beta", "app"]


async def test_the_emitted_order_is_the_collection_order() -> None:
    container = _compile(
        _definition(Plugin, Second, qualifier="b"),
        _definition(Plugin, First, qualifier="a"),
    )

    plugins = await container.get(Sequence[Plugin])

    assert [plugin.name() for plugin in plugins] == ["Second", "First"]


async def test_every_kind_is_resolvable() -> None:
    instance = Buffer()
    container = _compile(
        _definition(Plugin, First, qualifier="class"),
        _definition(Buffer, instance, kind="instance"),
        _definition(Declared, Declared, kind="declared"),
        _definition(Third, third, kind="factory"),
    )

    assert isinstance(await container.get(Plugin, "class"), First)
    assert await container.get(Buffer) is instance
    assert isinstance(await container.get(Declared), Declared)
    assert isinstance(await container.get(Third), Third)


async def test_a_resettable_service_is_tracked_once_built() -> None:
    tracked: list[tuple[object, str]] = []
    definition = Definition(
        (Buffer, None), buffer_resource, "factory", "singleton", ALPHA, reset_method="reset"
    )
    container = _compile(definition, tracked=tracked)
    assert tracked == []

    built = await container.get(Buffer)

    assert tracked == [(built, "reset")]


async def test_a_decoration_takes_the_original_key() -> None:
    container = _compile(
        _definition(Plugin, First),
        decorations={(Plugin, None): [Decoration(Loud, "inner", "tests:Loud")]},
    )

    plugin = await container.get(Plugin)

    assert plugin.name() == "Loud(First)"


async def test_stacked_decorations_wrap_in_order() -> None:
    loud = Decoration(Loud, "inner", "tests:Loud")
    container = _compile(_definition(Plugin, First), decorations={(Plugin, None): [loud, loud]})

    plugin = await container.get(Plugin)

    assert plugin.name() == "Loud(Loud(First))"


def test_a_wireup_error_is_annotated_with_origins() -> None:
    with pytest.raises(WireupError) as caught:
        _ = _compile(_definition(NeedsMissing, NeedsMissing, BETA))

    assert any("is defined by bundle beta" in note for note in caught.value.__notes__)


async def test_parameters_reach_the_container() -> None:
    container = compile_container(
        [], [], parameters={"kernel": {"environment": "dev"}}, concurrent_scoped_access=False
    )

    assert container.config.get("kernel.environment") == "dev"
