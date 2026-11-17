"""A context for a new connection: what the server put there, without an earlier request's work."""

from __future__ import annotations

from contextvars import ContextVar

import pytest
from starlette.applications import Starlette
from starlette.requests import HTTPConnection

from tests.fixtures.app_kernel.services import Greeter
from tests.support.bundles import ChorusBundle, EchoBundle
from xtr_dependency_injection import Kernel, current_unit_of_work
from xtr_dependency_injection.exception import (
    DetachedVariableConflictError,
    FastapiIntegrationError,
)
from xtr_dependency_injection.integration import detached_context, register_detached_variable
from xtr_dependency_injection.integration.fastapi import (
    attach,
    current_connection,
    provider,
    request_scope,
)

pytestmark = pytest.mark.anyio

_TRACE: ContextVar[str] = ContextVar("test_detached_context_trace", default="none")
_REQUEST: ContextVar[str | None] = ContextVar("test_detached_context_request", default=None)
_TWICE: ContextVar[str | None] = ContextVar("test_detached_context_twice", default=None)
_CONFLICTING: ContextVar[str | None] = ContextVar("test_detached_context_conflict", default=None)


def _served_app() -> Starlette:
    app = Starlette()
    kernel = Kernel(
        "tests.fixtures.app_kernel",
        bundles={EchoBundle: {"all": True}, ChorusBundle: {"all": True}},
    )
    attach(app, kernel.with_env("test").build())
    return app


async def test_a_detached_context_has_no_unit_and_no_connection() -> None:
    app = _served_app()
    connection = HTTPConnection({"type": "http", "app": app})

    async with request_scope(app, connection.scope):
        _ = await provider("service", Greeter, None)(connection)
        assert current_unit_of_work() is not None
        detached = detached_context()

    def read() -> bool:
        with pytest.raises(FastapiIntegrationError, match="can only be read"):
            _ = current_connection()
        return current_unit_of_work() is None

    assert detached.run(read)


async def test_a_detached_context_keeps_what_else_the_context_held() -> None:
    _ = _TRACE.set("span-1")

    detached = detached_context()

    assert detached.run(_TRACE.get) == "span-1"


async def test_detaching_leaves_the_calling_context_as_it_was() -> None:
    app = _served_app()
    connection = HTTPConnection({"type": "http", "app": app})

    async with request_scope(app, connection.scope):
        _ = await provider("service", Greeter, None)(connection)
        _ = detached_context()

        assert current_unit_of_work() is not None
        assert current_connection() is connection


async def test_registered_variables_are_reset_in_a_detached_context() -> None:
    register_detached_variable(_REQUEST, None)
    _ = _REQUEST.set("first request")

    detached = detached_context()

    assert detached.run(_REQUEST.get) is None
    assert _REQUEST.get() == "first request"


async def test_registering_the_same_variable_twice_is_a_no_op() -> None:
    register_detached_variable(_TWICE, None)
    register_detached_variable(_TWICE, None)
    _ = _TWICE.set("first request")

    assert detached_context().run(_TWICE.get) is None


async def test_registering_a_variable_with_another_value_raises() -> None:
    register_detached_variable(_CONFLICTING, None)

    with pytest.raises(DetachedVariableConflictError, match="test_detached_context_conflict"):
        register_detached_variable(_CONFLICTING, "other")
