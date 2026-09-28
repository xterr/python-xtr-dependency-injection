"""The seam and resolvers the injection markers hand the web framework."""

from __future__ import annotations

import types
from typing import TYPE_CHECKING

import pytest
from starlette.applications import Starlette
from starlette.requests import HTTPConnection

from tests.fixtures.app_kernel.services import Greeter
from tests.support.bundles import ChorusBundle, EchoBundle
from xtr_dependency_injection import Kernel
from xtr_dependency_injection.exception import FastapiIntegrationError
from xtr_dependency_injection.integration.fastapi import attach, detach, provider, request_scope

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
    resolve = provider("service", Greeter, None)

    async with request_scope(app):
        greeter = await resolve()

    assert isinstance(greeter, Greeter)
    # The fixture kernel uppercases the greeting and decorates the echo.
    assert greeter.greet() == "please, HELLO!"


@pytest.mark.anyio
async def test_the_param_resolver_reads_the_attached_container() -> None:
    request = HTTPConnection({"type": "http", "app": _served_app()})
    resolve = provider("param", "app.punctuation")

    value = await resolve(request)

    assert value == "!"


@pytest.mark.anyio
async def test_the_env_resolver_reads_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XTR_FASTAPI_TEST_GREETING", "hi")
    request = HTTPConnection({"type": "http", "app": _served_app()})
    resolve = provider("env", "XTR_FASTAPI_TEST_GREETING")

    value = await resolve(request)

    assert value == "hi"


@pytest.mark.anyio
async def test_the_service_resolver_without_an_open_scope_says_so() -> None:
    resolve = provider("service", Service, None)

    with pytest.raises(FastapiIntegrationError, match="no kernel serves this application"):
        _ = await resolve()


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["param", "env"])
async def test_a_connection_resolver_without_an_attached_kernel_says_so(
    kind: Literal["param", "env"],
) -> None:
    request = HTTPConnection({"type": "http", "app": Starlette()})
    resolve = provider(kind, "unserved")

    with pytest.raises(FastapiIntegrationError, match="no kernel serves this application"):
        _ = await resolve(request)


@pytest.mark.anyio
async def test_a_request_scope_without_an_attached_kernel_says_so() -> None:
    with pytest.raises(FastapiIntegrationError, match="no kernel serves this application"):
        async with request_scope(Starlette()):
            pytest.fail("the scope must not open without a kernel")


@pytest.mark.anyio
async def test_the_scope_exits_and_the_resolvers_reset_when_the_body_raises() -> None:
    app = _served_app()
    resolve = provider("service", Greeter, None)

    async def resolve_then_raise() -> None:
        async with request_scope(app):
            _ = await resolve()  # the scope is open: resolution works
            msg = "boom"
            raise RuntimeError(msg)

    with pytest.raises(RuntimeError, match="boom"):
        await resolve_then_raise()

    with pytest.raises(FastapiIntegrationError, match="no kernel serves this application"):
        _ = await resolve()
