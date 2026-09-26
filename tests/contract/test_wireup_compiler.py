"""The compiler against a real wireup container: kinds, order, reset, decoration, errors."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from typing import Annotated, Literal

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
from xtr_dependency_injection.decorator.as_decorator import AutowireDecorated

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
    def __init__(self, inner: Annotated[Plugin, AutowireDecorated()]) -> None:
        self.inner: Plugin = inner

    @override
    def name(self) -> str:
        return f"Loud({self.inner.name()})"


class Missing:
    pass


class NeedsMissing:
    def __init__(self, missing: Missing) -> None:
        self.missing: Missing = missing


def third() -> Third:
    return Third()


def buffer_resource() -> Iterator[Buffer]:
    yield Buffer()


Kind = Literal["class", "factory", "instance"]


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


def test_emission_order_is_priority_desc_then_definition_order() -> None:
    app = _definition(Plugin, First, APP, qualifier="app")
    beta = _definition(Plugin, Second, BETA, qualifier="beta")
    alpha_low = _definition(Plugin, Third, ALPHA, qualifier="alpha_low")
    alpha_high = _definition(Plugin, Third, ALPHA, qualifier="alpha_high", priority=5)
    kernel = _definition(Plugin, First, KERNEL, qualifier="kernel")

    ordered = emission_order([app, beta, alpha_low, alpha_high, kernel])

    assert [d.key[1] for d in ordered] == ["alpha_high", "app", "beta", "alpha_low", "kernel"]


def test_a_forwarding_definition_follows_its_target() -> None:
    first = _definition(First, First, APP, priority=1)
    second = _definition(Second, Second, APP, priority=9)
    first_alias = _definition(Plugin, First, APP, qualifier="first")
    second_alias = _definition(Plugin, Second, APP, qualifier="second")
    forwards: dict[ServiceKey, ServiceKey] = {
        (Plugin, "first"): (First, None),
        (Plugin, "second"): (Second, None),
    }

    ordered = emission_order([first_alias, second_alias, first, second], forwards)

    assert [d.key for d in ordered] == [
        (Second, None),
        (Plugin, "second"),
        (First, None),
        (Plugin, "first"),
    ]


def test_a_forwarding_definition_whose_target_is_gone_comes_last() -> None:
    first = _definition(First, First, APP)
    orphan = _definition(Plugin, Second, APP, qualifier="orphan")

    forwards: dict[ServiceKey, ServiceKey] = {(Plugin, "orphan"): (Second, None)}

    ordered = emission_order([orphan, first], forwards)

    assert [d.key for d in ordered] == [(First, None), (Plugin, "orphan")]


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
        _definition(Third, third, kind="factory"),
    )

    assert isinstance(await container.get(Plugin, "class"), First)
    assert await container.get(Buffer) is instance
    assert isinstance(await container.get(Third), Third)


async def test_a_resettable_service_is_tracked_once_built() -> None:
    tracked: list[tuple[object, str]] = []
    definition = Definition((Buffer, None), buffer_resource, "factory", "singleton", ALPHA).add_tag(
        "kernel.reset", method="reset"
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
    from xtr_dependency_injection.exception import ContainerCompilationError  # noqa: PLC0415

    with pytest.raises(ContainerCompilationError) as caught:
        _ = _compile(_definition(NeedsMissing, NeedsMissing, BETA))

    assert isinstance(caught.value.__cause__, WireupError)
    assert any("is defined by bundle beta" in note for note in caught.value.__notes__)


async def test_parameters_reach_the_container() -> None:
    container = compile_container(
        [], [], parameters={"kernel": {"environment": "dev"}}, concurrent_scoped_access=False
    )

    assert container.config.get("kernel.environment") == "dev"


async def test_a_decorated_instance_builds_and_behaves() -> None:
    instance = First()
    container = _compile(
        _definition(Plugin, instance, kind="instance"),
        decorations={(Plugin, None): [Decoration(Loud, "inner", "tests:Loud")]},
    )

    plugin = await container.get(Plugin)

    assert plugin.name() == "Loud(First)"


async def test_a_reset_tagged_instance_is_tracked_once_built() -> None:
    tracked: list[tuple[object, str]] = []
    instance = Buffer()
    definition = Definition((Buffer, None), instance, "instance", "singleton", ALPHA).add_tag(
        "kernel.reset", method="reset"
    )
    container = _compile(definition, tracked=tracked)

    built = await container.get(Buffer)

    assert built is instance
    assert tracked == [(built, "reset")]


class Mailer:
    pass


class MailerFactory:
    pass


class NeedsMailerFactory:
    def __init__(self, factory: MailerFactory) -> None:
        self.factory: MailerFactory = factory


def test_a_note_matches_type_names_by_word_boundary() -> None:
    from xtr_dependency_injection.exception import ContainerCompilationError  # noqa: PLC0415

    # NeedsMailerFactory needs MailerFactory (unregistered); the message names
    # "MailerFactory". A substring match would also note the unrelated `Mailer`
    # definition — `\bMailer\b` in "MailerFactory" is what we prove absent.
    mailer_def = _definition(Mailer, Mailer, BETA)
    with pytest.raises(ContainerCompilationError) as caught:
        _ = _compile(mailer_def, _definition(NeedsMailerFactory, NeedsMailerFactory, BETA))

    notes = caught.value.__notes__
    assert not any("tests:Mailer is defined" in note for note in notes), notes
