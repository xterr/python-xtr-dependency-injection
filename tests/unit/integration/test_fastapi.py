"""The seam and resolvers the injection markers hand the web framework."""

from __future__ import annotations

import contextvars
import types
from typing import TYPE_CHECKING

import pytest
from starlette.applications import Starlette
from starlette.requests import HTTPConnection

from tests.fixtures.app_env import AsyncSession, MailBundle
from tests.fixtures.app_kernel.services import Greeter
from tests.support.bundles import ChorusBundle, EchoBundle
from xtr_dependency_injection import Kernel, current_unit_of_work
from xtr_dependency_injection.exception import FastapiIntegrationError
from xtr_dependency_injection.integration.fastapi import (
    attach,
    connection_of,
    current_connection,
    detach,
    provider,
    request_scope,
)

if TYPE_CHECKING:
    from typing import Literal

    from xtr_dependency_injection.kernel.compiled_kernel import CompiledKernel


class Service:
    """A service type a resolver is derived for."""


def _named(resolver: object) -> str:
    assert isinstance(resolver, types.FunctionType)
    return resolver.__name__


def _compiled() -> CompiledKernel:
    kernel = Kernel(
        "tests.fixtures.app_kernel",
        bundles={EchoBundle: {"all": True}, ChorusBundle: {"all": True}},
    )
    return kernel.with_env("test").build()


def _served_app() -> Starlette:
    app = Starlette()
    attach(app, _compiled())
    return app


def _connection(app: Starlette) -> HTTPConnection:
    """Build what the framework hands a resolver for a request of ``app``."""
    return HTTPConnection({"type": "http", "app": app})


def test_one_resolver_per_kind_key_and_qualifier() -> None:
    assert provider("service", Service, None) is provider("service", Service, None)
    assert provider("service", Service, "a") is not provider("service", Service, None)
    assert provider("param", "kernel.name") is provider("param", "kernel.name")
    assert provider("env", "int:PORT") is not provider("param", "int:PORT")


def test_a_resolver_is_flagged_and_named() -> None:
    resolve = provider("param", "kernel.name")

    assert getattr(resolve, "__xtr_provider__", False) is True
    assert _named(resolve) == "xtr_param[kernel.name]"
    assert _named(provider("service", Service, None)) == "xtr_service[Service]"


def test_attach_twice_without_detach_is_refused() -> None:
    app = _served_app()

    with pytest.raises(FastapiIntegrationError, match="already serves"):
        attach(app, _compiled())


def test_detach_removes_the_kernel_and_is_a_no_op_when_absent() -> None:
    app = Starlette()

    detach(app)  # nothing attached: a no-op

    attach(app, _compiled())
    detach(app)
    attach(app, _compiled())  # detaching made room for another kernel


@pytest.mark.anyio
async def test_the_service_resolver_resolves_inside_a_request_scope() -> None:
    app = _served_app()
    connection = _connection(app)
    resolve = provider("service", Greeter, None)

    async with request_scope(app, connection.scope):
        greeter = await resolve(connection)

    assert isinstance(greeter, Greeter)
    # The fixture kernel uppercases the greeting and decorates the echo.
    assert greeter.greet() == "please, HELLO!"


@pytest.mark.anyio
async def test_a_request_is_the_unit_of_work_what_it_starts_joins() -> None:
    app = Starlette()
    kernel = Kernel(
        "tests.fixtures.app_env",
        bundles={MailBundle: {"all": True}},
        env="test",
        environ={"MAIL_PORT": "2525"},
    )
    attach(app, kernel.build())
    connection = _connection(app)
    resolve = provider("service", AsyncSession, None)

    async with request_scope(app, connection.scope):
        session = await resolve(connection)
        unit = current_unit_of_work()
        assert unit is not None
        assert await unit.get(AsyncSession) is session

    assert current_unit_of_work() is None


@pytest.mark.anyio
async def test_the_param_resolver_reads_the_attached_container() -> None:
    request = _connection(_served_app())
    resolve = provider("param", "app.punctuation")

    value = await resolve(request)

    assert value == "!"


@pytest.mark.anyio
async def test_the_env_resolver_reads_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XTR_FASTAPI_TEST_GREETING", "hi")
    request = _connection(_served_app())
    resolve = provider("env", "XTR_FASTAPI_TEST_GREETING")

    value = await resolve(request)

    assert value == "hi"


@pytest.mark.anyio
async def test_the_service_resolver_without_an_open_scope_says_so() -> None:
    resolve = provider("service", Service, None)

    with pytest.raises(FastapiIntegrationError, match="no request scope is open") as raised:
        _ = await resolve(_connection(Starlette()))

    assert "setup(app, kernel)" in raised.value.reason


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["param", "env"])
async def test_a_connection_resolver_without_an_attached_kernel_says_so(
    kind: Literal["param", "env"],
) -> None:
    request = _connection(Starlette())
    resolve = provider(kind, "unserved")

    with pytest.raises(FastapiIntegrationError, match="no kernel serves this application"):
        _ = await resolve(request)


@pytest.mark.anyio
async def test_a_request_scope_without_an_attached_kernel_says_so() -> None:
    app = Starlette()

    with pytest.raises(FastapiIntegrationError, match="no kernel serves this application"):
        async with request_scope(app, _connection(app).scope):
            pytest.fail("the scope must not open without a kernel")


@pytest.mark.anyio
async def test_the_scope_exits_and_the_resolvers_reset_when_the_body_raises() -> None:
    app = _served_app()
    connection = _connection(app)
    resolve = provider("service", Greeter, None)

    async def resolve_then_raise() -> None:
        async with request_scope(app, connection.scope):
            _ = await resolve(connection)  # the scope is open: resolution works
            msg = "boom"
            raise RuntimeError(msg)

    with pytest.raises(RuntimeError, match="boom"):
        await resolve_then_raise()

    with pytest.raises(FastapiIntegrationError, match="no request scope is open"):
        _ = await resolve(connection)


@pytest.mark.anyio
async def test_a_resolver_publishes_the_connection_until_the_scope_exits() -> None:
    app = _served_app()
    connection = _connection(app)
    resolve = provider("service", Greeter, None)

    async with request_scope(app, connection.scope):
        _ = await resolve(connection)

        assert current_connection() is connection

    with pytest.raises(FastapiIntegrationError, match="only be read while a request is served"):
        _ = current_connection()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("kind", "key"), [("param", "app.punctuation"), ("env", "XTR_FASTAPI_TEST_GREETING")]
)
async def test_a_connection_resolver_publishes_in_the_scope_open_on_its_connection(
    kind: Literal["param", "env"], key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XTR_FASTAPI_TEST_GREETING", "hi")
    app = _served_app()
    connection = _connection(app)

    async with request_scope(app, connection.scope):
        _ = await provider(kind, key)(connection)

        assert current_connection() is connection


@pytest.mark.anyio
async def test_the_published_connection_is_read_off_its_own_scope() -> None:
    app = _served_app()
    connection = _connection(app)
    resolve = provider("service", Greeter, None)

    async with request_scope(app, connection.scope):
        assert connection_of(connection.scope) is None  # no marker has resolved yet
        _ = await resolve(connection)

        assert connection_of(connection.scope) is connection

    assert connection_of(connection.scope) is None


def test_reading_the_connection_outside_a_request_says_so() -> None:
    with pytest.raises(FastapiIntegrationError, match="can only be read") as raised:
        _ = current_connection()

    assert "a route that declared no marker" in raised.value.reason


@pytest.mark.anyio
async def test_a_service_resolver_that_finds_no_scope_publishes_nothing() -> None:
    resolve = provider("service", Service, None)

    with pytest.raises(FastapiIntegrationError, match="no request scope is open"):
        _ = await resolve(_connection(Starlette()))

    with pytest.raises(FastapiIntegrationError, match="can only be read"):
        _ = current_connection()


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["param", "env"])
async def test_a_connection_resolver_that_finds_no_kernel_publishes_nothing(
    kind: Literal["param", "env"],
) -> None:
    resolve = provider(kind, "unpublished")

    with pytest.raises(FastapiIntegrationError, match="no kernel serves this application"):
        _ = await resolve(_connection(Starlette()))

    with pytest.raises(FastapiIntegrationError, match="can only be read"):
        _ = current_connection()


@pytest.mark.anyio
async def test_a_nested_scope_reads_the_connection_the_outer_one_published() -> None:
    app = _served_app()
    outer = _connection(app)
    resolve = provider("service", Greeter, None)

    async with request_scope(app, outer.scope):
        _ = await resolve(outer)

        # Opened again on the same connection: the one request, served deeper.
        async with request_scope(app, outer.scope):
            assert current_connection() is outer


@pytest.mark.anyio
async def test_a_nested_scope_hands_the_outer_connection_back_when_it_exits() -> None:
    app = _served_app()
    outer = _connection(app)
    inner = HTTPConnection(outer.scope)
    resolve = provider("service", Greeter, None)

    async with request_scope(app, outer.scope):
        _ = await resolve(outer)

        async with request_scope(app, outer.scope):
            _ = await resolve(inner)
            assert current_connection() is inner

        assert current_connection() is outer


@pytest.mark.anyio
async def test_a_request_started_from_anothers_context_reads_nothing_of_it() -> None:
    app = _served_app()
    first, second = _connection(app), _connection(app)
    resolve = provider("service", Greeter, None)

    async with request_scope(app, first.scope):
        _ = await resolve(first)

        # The second request starts with everything the first one's context
        # holds — the way a server may start a task — but on its own connection.
        async with request_scope(app, second.scope):
            assert connection_of(second.scope) is None
            with pytest.raises(FastapiIntegrationError, match="can only be read"):
                _ = current_connection()

        assert current_connection() is first


@pytest.mark.anyio
async def test_a_marker_resolves_from_the_scope_open_on_its_own_connection() -> None:
    app = Starlette()
    kernel = Kernel(
        "tests.fixtures.app_env",
        bundles={MailBundle: {"all": True}},
        env="test",
        environ={"MAIL_PORT": "2525"},
    )
    attach(app, kernel.build())
    first, second = _connection(app), _connection(app)
    resolve = provider("service", AsyncSession, None)

    async with request_scope(app, first.scope):
        session = await resolve(first)

        async with request_scope(app, second.scope):
            assert await resolve(second) is not session
            # Whichever scope is open here, the first connection's marker is
            # still served from the first connection's own.
            assert await resolve(first) is session


@pytest.mark.anyio
async def test_a_context_that_outlives_the_scope_reads_nothing_of_it() -> None:
    app = _served_app()
    connection = _connection(app)
    resolve = provider("service", Greeter, None)

    async with request_scope(app, connection.scope):
        _ = await resolve(connection)
        kept = contextvars.copy_context()

    def read() -> None:
        with pytest.raises(FastapiIntegrationError, match="can only be read"):
            _ = current_connection()

    kept.run(read)
