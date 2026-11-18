"""A ``type`` alias in any annotation the container reads means exactly what it stands for.

Regression. The engine under the container knows nothing of :class:`typing.TypeAliasType`, so
an alias left in an annotation named a service no one registered (the build failed), crashed
the build when a factory returned one, or — on a command, a handler, a listener — hid the
marker saying the container fills a parameter, which then went unfilled. Every place the
container reads an annotation is driven here against a real kernel: a constructor, a factory's
parameters and its return (plain, async, generator, async generator), a bound callable (how the
console, the message bus and the event dispatcher call a user's code) with its own signature or
one handed over, a hook, ``Kernel.run``, a served route, and a scanned module whose annotations
are evaluated lazily. Each shape an annotation takes — alone, chained, applied to arguments,
inside ``Annotated``, in a union, as a collection's member — is read as the alias's value.
"""

from __future__ import annotations

import importlib
import inspect
from collections.abc import AsyncIterator, Hashable, Iterator, Mapping, Sequence
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Annotated, Literal, cast, final, override

import httpx
import pytest
from fastapi import FastAPI

from xtr_dependency_injection import (
    Autowire,
    Bundle,
    Injected,
    Kernel,
    ServiceConfigurator,
    ServiceLocator,
    Target,
    as_bundle,
    bind_callable,
    is_container_supplied,
)
from xtr_dependency_injection.integration.fastapi import attach, request_scope
from xtr_dependency_injection.integration.wireup import engine_container
from xtr_dependency_injection.kernel.booted_kernel import call_injected

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable
    from types import FunctionType

    from starlette.types import Receive, Scope, Send

    from tests.support.modules import ScratchModules
    from xtr_dependency_injection.builder.container_builder import ContainerBuilder
    from xtr_dependency_injection.kernel.compiled_kernel import CompiledKernel

pytestmark = pytest.mark.anyio


@final
class Mailer:
    """What every alias below stands for, labelled by the factory that built it."""

    def __init__(self, label: str) -> None:
        self.label = label


@final
class Pager:
    """Registered only as optional: ``Pager | None`` is its key."""


type MailerAlias = Mailer
type Chained = MailerAlias
type PagerAlias = Pager
type InjectedMailer = Injected[Mailer]
type SmtpMailer = Annotated[Mailer, Target("smtp")]
type Qualified[S] = Annotated[S, Target("smtp")]
type Mailers = Sequence[Mailer]
type MailersByName = Mapping[Hashable, Mailer]
type MailerLocator = ServiceLocator[Mailer]
type Locator[S] = ServiceLocator[S]
type Environment = Annotated[str, Autowire(param="kernel.environment")]
type SmtpHost = Annotated[str, Autowire(env="SMTP_HOST")]
type MaybePager = Pager | None
type MaybeInjectedPager = Injected[Pager] | None
type Mailing = Iterator[Mailer]
type AsyncMailing = AsyncIterator[Mailer]
type Json = dict[str, Json] | list[Json] | str
type Format = Literal["txt", "json"]

LABELS = ["default", "smtp", "async", "generated", "async-generated", "iterated"]
QUALIFIERS: list[Hashable | None] = [
    None,
    "smtp",
    "async",
    "generated",
    "async-generated",
    "iterated",
]


def default_mailer() -> MailerAlias:
    return Mailer("default")


def smtp_mailer() -> Chained:
    return Mailer("smtp")


async def async_mailer() -> MailerAlias:
    return Mailer("async")


def generated_mailer() -> Mailing:
    yield Mailer("generated")


async def async_generated_mailer() -> AsyncMailing:
    yield Mailer("async-generated")


def iterated_mailer() -> Iterator[MailerAlias]:
    yield Mailer("iterated")


def maybe_pager() -> MaybePager:
    return Pager()


class Holds:
    """A consumer: what the container handed its one parameter."""

    held: object

    def __init__(self, held: object) -> None:
        self.held = held


class TakesAlias(Holds):
    def __init__(self, mailer: MailerAlias) -> None:
        super().__init__(mailer)


class TakesChainedAlias(Holds):
    def __init__(self, mailer: Chained) -> None:
        super().__init__(mailer)


class TakesInjectedAlias(Holds):
    def __init__(self, mailer: Injected[MailerAlias]) -> None:
        super().__init__(mailer)


class TakesAliasedMarker(Holds):
    def __init__(self, mailer: InjectedMailer) -> None:
        super().__init__(mailer)


class TakesInjected(Holds):
    def __init__(self, mailer: Injected[Mailer]) -> None:
        super().__init__(mailer)


class TakesTargetedAlias(Holds):
    def __init__(self, mailer: Annotated[Chained, Target("smtp")]) -> None:
        super().__init__(mailer)


class TakesAliasedTarget(Holds):
    def __init__(self, mailer: SmtpMailer) -> None:
        super().__init__(mailer)


class TakesAppliedAlias(Holds):
    def __init__(self, mailer: Qualified[Mailer]) -> None:
        super().__init__(mailer)


class TakesAppliedAliasOfAlias(Holds):
    def __init__(self, mailer: Qualified[Chained]) -> None:
        super().__init__(mailer)


class TakesAliasedSequence(Holds):
    def __init__(self, mailers: Mailers) -> None:
        super().__init__(mailers)


class TakesSequenceOfAlias(Holds):
    def __init__(self, mailers: Sequence[MailerAlias]) -> None:
        super().__init__(mailers)


class TakesAliasedMapping(Holds):
    def __init__(self, mailers: MailersByName) -> None:
        super().__init__(mailers)


class TakesMappingOfAlias(Holds):
    def __init__(self, mailers: Mapping[Hashable, Chained]) -> None:
        super().__init__(mailers)


class TakesAliasedLocator(Holds):
    def __init__(self, mailers: MailerLocator) -> None:
        super().__init__(mailers)


class TakesLocatorOfAlias(Holds):
    def __init__(self, mailers: ServiceLocator[MailerAlias]) -> None:
        super().__init__(mailers)


class TakesAppliedLocator(Holds):
    def __init__(self, mailers: Locator[Chained]) -> None:
        super().__init__(mailers)


class TakesAliasedParameter(Holds):
    def __init__(self, environment: Environment) -> None:
        super().__init__(environment)


class TakesAliasedEnvironmentVariable(Holds):
    def __init__(self, host: SmtpHost) -> None:
        super().__init__(host)


class TakesAliasedOptional(Holds):
    def __init__(self, pager: MaybePager) -> None:
        super().__init__(pager)


class TakesOptionalOfAlias(Holds):
    def __init__(self, pager: PagerAlias | None) -> None:
        super().__init__(pager)


class TakesAliasedOptionalMarker(Holds):
    def __init__(self, pager: MaybeInjectedPager) -> None:
        super().__init__(pager)


class TakesOptionalMarker(Holds):
    def __init__(self, pager: Injected[Pager] | None) -> None:
        super().__init__(pager)


class TakesAliasedDefaults(Holds):
    """Aliases nothing registers, each with a default: left for the default, as unaliased."""

    def __init__(self, payload: Json = "none", fmt: Format = "txt") -> None:
        super().__init__((payload, fmt))


@final
class Report:
    def __init__(self, held: object) -> None:
        self.held = held


def report(mailers: Mailers, smtp: SmtpMailer, located: Locator[MailerAlias]) -> Report:
    """A factory taking aliases."""
    return Report((mailers, smtp, located))


CONSUMERS: list[type[Holds]] = [
    TakesAlias,
    TakesChainedAlias,
    TakesTargetedAlias,
    TakesAliasedTarget,
    TakesAppliedAlias,
    TakesAppliedAliasOfAlias,
    TakesAliasedSequence,
    TakesSequenceOfAlias,
    TakesAliasedMapping,
    TakesMappingOfAlias,
    TakesAliasedLocator,
    TakesLocatorOfAlias,
    TakesAppliedLocator,
    TakesAliasedParameter,
    TakesAliasedEnvironmentVariable,
    TakesAliasedOptional,
    TakesOptionalOfAlias,
    TakesAliasedDefaults,
]


@final
@as_bundle("aliased")
class AliasedBundle(Bundle):
    @override
    def load_extension(
        self, config: object, services: ServiceConfigurator, builder: ContainerBuilder
    ) -> None:
        del config, builder
        _ = services.set(default_mailer)
        _ = services.set(smtp_mailer, qualifier="smtp")
        _ = services.set(async_mailer, qualifier="async")
        _ = services.set(generated_mailer, qualifier="generated")
        _ = services.set(async_generated_mailer, qualifier="async-generated")
        _ = services.set(iterated_mailer, qualifier="iterated")
        _ = services.set(maybe_pager)
        _ = services.set(report)
        for consumer in CONSUMERS:
            _ = services.set(consumer)


def _compiled() -> CompiledKernel:
    return Kernel(
        "json",
        resources=(),
        env="test",
        bundles={AliasedBundle: {"all": True}},
        environ={"SMTP_HOST": "mail.test"},
    ).build()


def _described(held: object) -> object:
    """What a test compares: a mailer's label, a collection's labels, a locator's names."""
    match held:
        case Mailer():
            return held.label
        case Pager():
            return "pager"
        case ServiceLocator():
            return list(cast("ServiceLocator[Mailer]", held).provided_services())
        case Mapping():
            return {
                key: _described(value)
                for key, value in cast("Mapping[Hashable, object]", held).items()
            }
        case tuple() | list():
            return [_described(item) for item in cast("Sequence[object]", held)]
        case _:
            return held


EXPECTED: dict[type[Holds], object] = {
    TakesAlias: "default",
    TakesChainedAlias: "default",
    TakesTargetedAlias: "smtp",
    TakesAliasedTarget: "smtp",
    TakesAppliedAlias: "smtp",
    TakesAppliedAliasOfAlias: "smtp",
    TakesAliasedSequence: LABELS,
    TakesSequenceOfAlias: LABELS,
    TakesAliasedMapping: dict(zip(QUALIFIERS, LABELS, strict=True)),
    TakesMappingOfAlias: dict(zip(QUALIFIERS, LABELS, strict=True)),
    TakesAliasedLocator: QUALIFIERS,
    TakesLocatorOfAlias: QUALIFIERS,
    TakesAppliedLocator: QUALIFIERS,
    TakesAliasedParameter: "test",
    TakesAliasedEnvironmentVariable: "mail.test",
    TakesAliasedOptional: "pager",
    TakesOptionalOfAlias: "pager",
    TakesAliasedDefaults: ["none", "txt"],
}


def test_every_consumer_shape_has_an_expectation() -> None:
    assert set(EXPECTED) == set(CONSUMERS)


MARKED_CONSTRUCTORS: list[tuple[type[Holds], Callable[[], object], object]] = [
    (TakesInjected, default_mailer, "default"),
    (TakesInjectedAlias, default_mailer, "default"),
    (TakesAliasedMarker, default_mailer, "default"),
    (TakesOptionalMarker, maybe_pager, "pager"),
    (TakesAliasedOptionalMarker, maybe_pager, "pager"),
]


@pytest.mark.parametrize(
    ("consumer", "producer", "expected"),
    MARKED_CONSTRUCTORS,
    ids=[consumer.__name__ for consumer, _, _ in MARKED_CONSTRUCTORS],
)
async def test_a_marker_on_a_constructor_behaves_the_same_written_with_an_alias(
    consumer: type[Holds], producer: Callable[[], object], expected: object
) -> None:
    @as_bundle(f"marked_{consumer.__name__.lower()}")
    class MarkedBundle(Bundle):
        @override
        def load_extension(
            self, config: object, services: ServiceConfigurator, builder: ContainerBuilder
        ) -> None:
            del config, builder
            _ = services.set(producer)
            _ = services.set(consumer)

    # A constructor fills every parameter anyway: the engine calls the marker redundant,
    # whether it is written out or through an alias.
    with pytest.warns(UserWarning, match="Redundant Injected"):
        compiled = Kernel("json", resources=(), bundles={MarkedBundle: {"all": True}}).build()
    async with await compiled.boot() as booted:
        built = await booted.container.get(consumer)

    assert _described(built.held) == expected


@pytest.mark.parametrize("consumer", CONSUMERS, ids=[consumer.__name__ for consumer in CONSUMERS])
async def test_a_constructor_parameter_written_with_an_alias_is_injected(
    consumer: type[Holds],
) -> None:
    async with await _compiled().boot() as booted:
        built = await booted.container.get(consumer)

        assert _described(built.held) == EXPECTED[consumer]


async def test_a_factory_parameter_written_with_an_alias_is_injected() -> None:
    async with await _compiled().boot() as booted:
        built = await booted.container.get(Report)

    mailers, smtp, located = cast("tuple[object, object, object]", built.held)
    assert _described(mailers) == LABELS
    assert _described(smtp) == "smtp"
    assert _described(located) == QUALIFIERS


async def test_a_factory_returning_an_alias_is_registered_under_what_it_stands_for() -> None:
    compiled = _compiled()

    keys = {definition.key for definition in compiled.report.definitions}

    assert {(Mailer, qualifier) for qualifier in QUALIFIERS} <= keys
    assert (Pager | None, None) in keys
    assert not any(type(key[0]).__name__ == "TypeAliasType" for key in keys)


@pytest.mark.parametrize(
    ("qualifier", "label"),
    list(zip(QUALIFIERS, LABELS, strict=True)),
    ids=[str(qualifier) for qualifier in QUALIFIERS],
)
async def test_each_kind_of_factory_returning_an_alias_builds_by_the_type(
    qualifier: Hashable | None, label: str
) -> None:
    async with await _compiled().boot() as booted:
        built = await booted.container.get(Mailer, qualifier)

        assert built.label == label


async def test_an_optional_alias_return_is_the_optional_key() -> None:
    async with await _compiled().boot() as booted:
        built = await booted.container.get(cast("type[Pager]", Pager | None))

        assert isinstance(built, Pager)


async def _aliased_marker(mailer: InjectedMailer) -> object:
    return mailer


async def _injected_alias(mailer: Injected[MailerAlias]) -> object:
    return mailer


async def _aliased_target(mailer: SmtpMailer) -> object:
    return mailer


async def _applied_alias(mailer: Qualified[Chained]) -> object:
    return mailer


async def _targeted_alias(mailer: Annotated[MailerAlias, Target("smtp")]) -> object:
    return mailer


async def _aliased_locator(mailers: MailerLocator) -> object:
    return mailers


async def _applied_locator(mailers: Locator[MailerAlias]) -> object:
    return mailers


async def _injected_aliased_sequence(mailers: Injected[Mailers]) -> object:
    return mailers


async def _aliased_parameter(environment: Environment) -> object:
    return environment


async def _aliased_environment_variable(host: SmtpHost) -> object:
    return host


async def _aliased_optional_marker(pager: MaybeInjectedPager) -> object:
    return pager


async def _optional_marker(pager: Injected[Pager] | None) -> object:
    return pager


BOUND: list[tuple[FunctionType, object]] = [
    (_aliased_marker, "default"),
    (_injected_alias, "default"),
    (_aliased_target, "smtp"),
    (_applied_alias, "smtp"),
    (_targeted_alias, "smtp"),
    (_aliased_locator, QUALIFIERS),
    (_applied_locator, QUALIFIERS),
    (_injected_aliased_sequence, LABELS),
    (_aliased_parameter, "test"),
    (_aliased_environment_variable, "mail.test"),
    (_aliased_optional_marker, "pager"),
    (_optional_marker, "pager"),
]
BOUND_IDS = [target.__name__ for target, _ in BOUND]


def _only_annotation(target: Callable[..., object]) -> object:
    (parameter,) = inspect.signature(target, eval_str=True).parameters.values()
    return cast("object", parameter.annotation)


@pytest.mark.parametrize(("target", "expected"), BOUND, ids=BOUND_IDS)
async def test_a_bound_callable_gets_a_parameter_written_with_an_alias(
    target: Callable[..., object], expected: object
) -> None:
    # What the console, the bus and the dispatcher ask before leaving a parameter to the container.
    assert is_container_supplied(_only_annotation(target))

    async with await _compiled().boot() as booted:
        bound = bind_callable(booted.container, target)

        assert _described(await bound()) == expected


@pytest.mark.parametrize(("target", "expected"), BOUND, ids=BOUND_IDS)
async def test_a_bound_callable_given_its_signature_reads_it_through_aliases(
    target: Callable[..., object], expected: object
) -> None:
    # The console hands over the signature it read, aliases as written.
    signature = inspect.signature(target, eval_str=True)

    async with await _compiled().boot() as booted:
        bound = bind_callable(booted.container, target, signature=signature)

        assert _described(await bound()) == expected


@pytest.mark.parametrize(("target", "expected"), BOUND, ids=BOUND_IDS)
async def test_a_hook_gets_a_parameter_written_with_an_alias(
    target: Callable[..., object], expected: object
) -> None:
    async with await _compiled().boot() as booted:
        result = await call_injected(engine_container(booted), target)

        assert _described(result) == expected


async def test_a_caller_keeps_the_parameters_it_passes_written_with_aliases() -> None:
    async def command(fmt: Format, payload: Json, mailer: InjectedMailer) -> object:
        return fmt, payload, mailer

    # What the caller passes is the caller's, however it is written.
    assert not is_container_supplied(Format)
    assert not is_container_supplied(Json)

    async with await _compiled().boot() as booted:
        bound = bind_callable(booted.container, command)
        fmt, payload, mailer = cast(
            "tuple[object, object, object]", await bound("json", {"a": ["b"]})
        )

    assert (fmt, payload, _described(mailer)) == ("json", {"a": ["b"]}, "default")


def test_the_kernel_runs_a_main_taking_an_alias() -> None:
    async def main(mailer: InjectedMailer, mailers: Injected[Mailers]) -> int:
        return len(mailer.label) + len(mailers)

    kernel = Kernel(
        "json",
        resources=(),
        env="test",
        bundles={AliasedBundle: {"all": True}},
        environ={"SMTP_HOST": "mail.test"},
    )

    assert kernel.run(main) == len("default") + len(LABELS)


@final
class ScopePerRequest:
    """What a served application's kernel middleware does, and nothing else."""

    def __init__(self, app: FastAPI) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        async with request_scope(self._app, scope):
            await self._app(scope, receive, send)


def _application() -> FastAPI:
    app = FastAPI()
    attach(app, _compiled())

    @app.get("/aliased-marker")
    async def aliased_marker(mailer: InjectedMailer) -> dict[str, str]:
        return {"label": mailer.label}

    @app.get("/injected-alias")
    async def injected_alias(mailer: Injected[MailerAlias]) -> dict[str, str]:
        return {"label": mailer.label}

    @app.get("/aliased-target")
    async def aliased_target(mailer: SmtpMailer) -> dict[str, str]:
        return {"label": mailer.label}

    @app.get("/targeted-alias")
    async def targeted_alias(mailer: Annotated[Chained, Target("smtp")]) -> dict[str, str]:
        return {"label": mailer.label}

    @app.get("/aliased-parameter")
    async def aliased_parameter(environment: Environment) -> dict[str, str]:
        return {"label": environment}

    return app


@asynccontextmanager
async def _serving(app: FastAPI) -> AsyncGenerator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=ScopePerRequest(app))
    async with httpx.AsyncClient(transport=transport, base_url="http://served.test") as client:
        yield client


@pytest.mark.parametrize(
    ("path", "label"),
    [
        ("/aliased-marker", "default"),
        ("/injected-alias", "default"),
        ("/aliased-target", "smtp"),
        ("/targeted-alias", "smtp"),
        ("/aliased-parameter", "test"),
    ],
)
async def test_a_route_parameter_written_with_an_alias_is_injected(path: str, label: str) -> None:
    async with _serving(_application()) as client:
        response = await client.get(path)

    assert response.status_code == 200, response.text
    assert response.json() == {"label": label}


def test_a_route_parameter_written_with_an_alias_is_not_documented_as_a_request_parameter() -> None:
    schema = _application().openapi()

    paths = cast("dict[str, dict[str, dict[str, object]]]", schema["paths"])
    assert all("parameters" not in operation["get"] for operation in paths.values())


LAZY_APPLICATION = """
from collections.abc import Sequence
from typing import Annotated

from xtr_dependency_injection import AutowireDecorated, Injected, as_decorator, as_service, on_boot

BOOTED = []


class Mailer:
    def __init__(self, label: str) -> None:
        self.label = label


@as_service
class Uses:
    # Every alias is defined below: the annotations are read only when the container asks.
    def __init__(self, mailer: Later, mailers: LaterMany) -> None:
        self.held = (mailer, mailers)


@as_service
def make() -> Later:
    return Mailer("made")


@as_decorator(Mailer, priority=1)
class Loud(Mailer):
    def __init__(self, inner: Decorated) -> None:
        super().__init__(inner.label.upper())


@as_decorator(Mailer)
class Quiet(Mailer):
    def __init__(self, inner: Annotated[Later, AutowireDecorated()]) -> None:
        super().__init__(f"({inner.label})")


@on_boot
def boot(mailer: LaterInjected) -> None:
    BOOTED.append(mailer.label)


type Later = Mailer
type LaterMany = Sequence[Later]
type LaterInjected = Injected[Later]
type Decorated = Annotated[Later, AutowireDecorated()]
"""


async def test_a_scanned_application_without_the_future_import_reads_its_aliases(
    scratch_modules: ScratchModules,
) -> None:
    scratch_modules.write({"lazy_app.services": LAZY_APPLICATION})
    compiled = Kernel("lazy_app", bundles={}).build()

    async with await compiled.boot() as booted:
        services = vars(importlib.import_module("lazy_app.services"))
        uses = await booted.container.get(cast("type[Holds]", services["Uses"]))
        booted_labels = cast("list[str]", services["BOOTED"])

    mailer, mailers = cast("tuple[object, object]", uses.held)
    # Decorated by both spellings of the decorated parameter: Loud first, then Quiet around it.
    assert _label_of(mailer) == "(MADE)"
    assert [_label_of(item) for item in cast("Sequence[object]", mailers)] == ["(MADE)"]
    # A hook takes the injected alias.
    assert booted_labels == ["(MADE)"]


def _label_of(mailer: object) -> str:
    return cast("str", getattr(mailer, "label"))  # noqa: B009 — a class of the scratch module
