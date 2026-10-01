"""A ``ServiceLocator[T]`` parameter is filled by the container, lazily and in scope.

End-to-end against a real kernel: a bare ``ServiceLocator[T]`` in a constructor, a
factory, a hook, a bound callable (the console's path) and a served route each
receives a locator whose keys match ``Mapping[Hashable, T]`` but whose entries are
built only when asked for by name — in the scope the consumer was resolved in.
"""

from __future__ import annotations

from collections.abc import Hashable, Mapping
from typing import TYPE_CHECKING, cast, final

import pytest
from starlette.applications import Starlette
from typing_extensions import override

from tests.fixtures.app_tagged_aliases import Step as AliasedStep
from xtr_dependency_injection import (
    Bundle,
    Injected,
    Kernel,
    ServiceConfigurator,
    ServiceLocator,
    as_bundle,
    bind_callable,
    is_container_supplied,
    unit_of_work,
)
from xtr_dependency_injection.exception import ServiceResolutionError, UnknownLocatorKeyError
from xtr_dependency_injection.integration.fastapi import attach, provider, request_scope
from xtr_dependency_injection.integration.wireup import engine_container
from xtr_dependency_injection.kernel.booted_kernel import call_injected

if TYPE_CHECKING:
    from xtr_dependency_injection.builder.container_builder import ContainerBuilder
    from xtr_dependency_injection.kernel.compiled_kernel import CompiledKernel

pytestmark = pytest.mark.anyio


class Handler:
    """A member built by a counting factory, to watch when it is built."""

    label: str

    def __init__(self, label: str) -> None:
        self.label = label


class Session:
    """A scoped member, one per unit of work."""


class Widget:
    """A type nothing registers — a requested but empty locator's member."""


BUILDS: list[str] = []
SEEN: dict[str, ServiceLocator[Handler]] = {}


def _handler(label: str) -> Handler:
    BUILDS.append(label)
    return Handler(label)


def _auth_handler() -> Handler:
    return _handler("auth")


def _log_handler() -> Handler:
    return _handler("log")


@final
class UsesLocator:
    """A singleton consumer taking a locator and the eager mapping beside it."""

    def __init__(
        self, handlers: ServiceLocator[Handler], eager: Mapping[Hashable, Handler]
    ) -> None:
        self.handlers = handlers
        self.eager_keys = list(eager)


@final
class LocatorOnly:
    """A consumer taking only the locator, so nothing eager builds its members."""

    def __init__(self, handlers: ServiceLocator[Handler]) -> None:
        self.handlers = handlers


@final
class WantsEmpty:
    """A consumer of a locator over a type nothing registers."""

    def __init__(self, widgets: ServiceLocator[Widget]) -> None:
        self.widgets = widgets


@final
class UsesScoped:
    """A scoped consumer whose locator must resolve its scoped member in-scope."""

    def __init__(self, sessions: ServiceLocator[Session]) -> None:
        self.sessions = sessions


@final
class Recorder:
    """What a factory taking a locator produces, to prove factory injection."""


def _record(handlers: ServiceLocator[Handler]) -> Recorder:
    SEEN["handlers"] = handlers
    return Recorder()


@final
@as_bundle("locators")
class LocatorBundle(Bundle):
    @override
    def load_extension(
        self, config: object, services: ServiceConfigurator, builder: ContainerBuilder
    ) -> None:
        del config, builder
        _ = services.set(_auth_handler, qualifier="auth")
        _ = services.set(_log_handler, qualifier="log")
        _ = services.set(Session, lifetime="scoped")
        _ = services.set(UsesLocator)
        _ = services.set(LocatorOnly)
        _ = services.set(WantsEmpty)
        _ = services.set(UsesScoped, lifetime="scoped")
        _ = services.set(_record)


def _compiled() -> CompiledKernel:
    return Kernel("json", resources=(), bundles={LocatorBundle: {"all": True}}).build()


@pytest.fixture(autouse=True)
def _reset_state() -> None:
    BUILDS.clear()
    SEEN.clear()


async def test_a_constructor_receives_a_lazy_locator_keyed_like_the_mapping() -> None:
    async with await _compiled().boot() as booted:
        uses = await booted.container.get(UsesLocator)

        assert list(uses.handlers.provided_services()) == uses.eager_keys
        assert list(uses.handlers.provided_services()) == ["auth", "log"]


async def test_the_locators_entries_are_not_built_until_asked_for() -> None:
    async with await _compiled().boot() as booted:
        uses = await booted.container.get(LocatorOnly)
        assert BUILDS == []

        handler = await uses.handlers.get("auth")

        assert handler.label == "auth"
        assert BUILDS == ["auth"]


async def test_an_unknown_name_raises_unknown_locator_key_error() -> None:
    async with await _compiled().boot() as booted:
        uses = await booted.container.get(LocatorOnly)

        with pytest.raises(UnknownLocatorKeyError) as caught:
            _ = await uses.handlers.get("absent")

        assert isinstance(caught.value, LookupError)
        assert caught.value.known == ("auth", "log")


async def test_a_type_with_no_members_yields_an_empty_locator() -> None:
    async with await _compiled().boot() as booted:
        wants = await booted.container.get(WantsEmpty)

        assert len(wants.widgets) == 0
        assert dict(wants.widgets.provided_services()) == {}


async def test_a_scoped_member_resolves_from_the_consumers_own_scope() -> None:
    async with await _compiled().boot() as booted, unit_of_work(booted.container) as unit:
        uses = await unit.get(UsesScoped)
        session = await uses.sessions.get(None)
        other = await unit.get(Session)

        assert isinstance(session, Session)
        assert session is other  # the unit's one, shared


async def test_a_scoped_membered_locator_cannot_be_resolved_from_the_root() -> None:
    async with await _compiled().boot() as booted:
        with pytest.raises(ServiceResolutionError) as caught:
            _ = await booted.container.get(ServiceLocator[Session])

        assert "scope" in str(caught.value).lower()


async def test_a_root_locator_gives_the_scope_error_for_a_scoped_entry() -> None:
    async with await _compiled().boot() as booted:
        # The public constructor lets a root-container locator hold a scoped key.
        locator: ServiceLocator[Session] = ServiceLocator(
            booted.container, {"session": (Session, None)}
        )

        with pytest.raises(ServiceResolutionError) as caught:
            _ = await locator.get("session")

        assert "scope" in str(caught.value).lower()


async def test_a_factory_parameter_receives_the_locator() -> None:
    async with await _compiled().boot() as booted:
        _ = await booted.container.get(Recorder)

        assert list(SEEN["handlers"].provided_services()) == ["auth", "log"]


async def test_a_hook_style_injection_fills_the_locator() -> None:
    async def warm(handlers: Injected[ServiceLocator[Handler]]) -> list[Hashable]:
        return list(handlers.provided_services())

    async with await _compiled().boot() as booted:
        result = await call_injected(engine_container(booted), warm)

        assert result == ["auth", "log"]


async def test_a_bound_callable_receives_a_bare_locator_the_console_way() -> None:
    async def command(handlers: ServiceLocator[Handler]) -> list[Hashable]:
        return list(handlers.provided_services())

    assert is_container_supplied(ServiceLocator[Handler])  # what the console asks

    async with await _compiled().boot() as booted:
        bound = bind_callable(booted.container, command)

        assert await bound() == ["auth", "log"]


async def test_a_served_route_resolves_the_locator_through_the_marker() -> None:
    app = Starlette()
    attach(app, _compiled())
    resolve = provider("service", ServiceLocator[Handler], None)

    async with request_scope(app):
        handlers = cast("ServiceLocator[Handler]", await resolve())

    assert list(handlers.provided_services()) == ["auth", "log"]


async def test_a_locators_keys_match_the_mapping_for_aliased_and_tagged_members() -> None:
    compiled = Kernel("tests.fixtures.app_tagged_aliases", bundles={}).build()
    async with await compiled.boot() as booted:
        locator = await booted.container.get(ServiceLocator[AliasedStep])
        mapping = await booted.container.get(Mapping[Hashable, AliasedStep])

        assert list(locator.provided_services()) == list(mapping)
        assert list(locator.provided_services()) == ["gamma", "alpha", "delta", "beta"]
        assert (await locator.get("alpha")).__class__.__name__ == "Alpha"
