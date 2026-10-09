"""The connection a resolver publishes, read back by what the container builds.

Driven the way a server drives an application — through an ASGI transport,
against a real kernel, with one container scope per request — because the
behaviour under test is the framework's own request object reaching a factory
the container runs, and only a served request produces that object.
"""

from __future__ import annotations

import random
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, cast, final

import anyio
import httpx
import pytest
from fastapi import BackgroundTasks, FastAPI, Request, WebSocket
from typing_extensions import override

from xtr_dependency_injection import Bundle, Injected, Kernel, ServiceConfigurator, as_bundle
from xtr_dependency_injection.integration.fastapi import attach, current_connection, request_scope

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from starlette.requests import HTTPConnection
    from starlette.types import ASGIApp, Message, Receive, Scope, Send

    from xtr_dependency_injection.builder.container_builder import ContainerBuilder

SEEN: dict[str, object] = {}
"""What one served request saw, read back by the test that drove it."""

DERIVED = frozenset({"operationId", "summary", "title"})
"""What the framework names after the endpoint function and its path."""

CONCURRENT = 50
"""How many requests the cross-talk test drives through the application at once."""

JITTER = random.Random(20251008)  # noqa: S311 — jitter in a test, not a secret
"""Seeded so the factories finish in an order unrelated to the one they started in."""


@final
class Caller:
    """A scoped service built for one request, holding the connection it read."""

    def __init__(self, connection: HTTPConnection) -> None:
        self.connection = connection


@final
class SlowCaller:
    """The same, built by a factory that gives the event loop other work first."""

    def __init__(self, connection: HTTPConnection) -> None:
        self.connection = connection


def _caller() -> Caller:
    """Build one request's caller, the way a per-request factory does."""
    return Caller(current_connection())


async def _slow_caller() -> SlowCaller:
    """Build one request's caller, reading only after other requests have run."""
    await anyio.sleep(JITTER.random() / 100)
    return SlowCaller(current_connection())


async def _record_after_the_response() -> None:
    """Read the connection from where the framework runs a background task."""
    SEEN["deferred"] = current_connection()


@final
@as_bundle("callers")
class CallerBundle(Bundle):
    @override
    def load_extension(
        self, config: object, services: ServiceConfigurator, builder: ContainerBuilder
    ) -> None:
        del config, builder
        _ = services.set(_caller, lifetime="scoped")
        _ = services.set(_slow_caller, lifetime="scoped")


@final
class ScopePerRequest:
    """What a served application's kernel middleware does, and nothing else."""

    def __init__(self, app: FastAPI) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        async with request_scope(self._app):
            await self._app(scope, receive, send)


def _application() -> FastAPI:
    app = FastAPI()
    attach(app, Kernel("json", resources=(), bundles={CallerBundle: {"all": True}}).build())

    @app.get("/served")
    async def served(request: Request, caller: Injected[Caller]) -> dict[str, str]:
        SEEN["request"] = request
        SEEN["published"] = current_connection()
        SEEN["built"] = caller.connection
        return {"path": caller.connection.url.path}

    @app.get("/served-sync")
    def served_sync(request: Request, caller: Injected[Caller]) -> dict[str, str]:
        SEEN["request"] = request
        SEEN["published"] = current_connection()
        SEEN["built"] = caller.connection
        return {"path": caller.connection.url.path}

    @app.get("/marked/{item_id}")
    async def marked(
        item_id: int, q: str, request: Request, caller: Injected[Caller]
    ) -> dict[str, int]:
        del request, caller
        return {"item": item_id, "q_length": len(q)}

    @app.get("/plain/{item_id}")
    async def plain(item_id: int, q: str) -> dict[str, int]:
        return {"item": item_id, "q_length": len(q)}

    @app.get("/concurrent/{token}")
    async def concurrent(token: int, caller: Injected[SlowCaller]) -> dict[str, str]:
        return {"path": caller.connection.url.path, "token": str(token)}

    @app.get("/deferred")
    async def deferred(
        request: Request, tasks: BackgroundTasks, caller: Injected[Caller]
    ) -> dict[str, str]:
        SEEN["request"] = request
        tasks.add_task(_record_after_the_response)
        return {"path": caller.connection.url.path}

    @app.websocket("/socket")
    async def socket(websocket: WebSocket, caller: Injected[Caller]) -> None:
        SEEN["request"] = websocket
        SEEN["published"] = current_connection()
        SEEN["built"] = caller.connection
        await websocket.accept()
        await websocket.close()

    return app


@asynccontextmanager
async def _serving(app: FastAPI) -> AsyncGenerator[httpx.AsyncClient, None]:
    """Serve ``app`` and yield a client driving it, one scope per request."""
    transport = httpx.ASGITransport(app=ScopePerRequest(app))
    async with httpx.AsyncClient(transport=transport, base_url="http://served.test") as client:
        yield client


def _socket_scope(path: str) -> Scope:
    """What a server hands an application for one WebSocket connection to ``path``."""
    return {
        "type": "websocket",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "scheme": "ws",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", b"served.test")],
        "client": ("127.0.0.1", 54321),
        "server": ("served.test", 80),
        "subprotocols": [],
    }


async def _handshake(app: ASGIApp, path: str) -> list[str]:
    """Drive one WebSocket connection through ``app``, returning what it sent.

    The ASGI transport speaks HTTP only, so the socket is driven the way a
    server would: the connect message in, whatever the application sends out.
    """
    incoming: list[Message] = [{"type": "websocket.connect"}]
    sent: list[str] = []

    async def receive() -> Message:
        return incoming.pop(0) if incoming else {"type": "websocket.disconnect", "code": 1000}

    async def send(message: Message) -> None:
        sent.append(cast("str", message["type"]))

    await app(_socket_scope(path), receive, send)
    return sent


def _documented(operation: dict[str, object]) -> dict[str, object]:
    """Return ``operation`` without what the framework names after the endpoint.

    The operation id, the summary and a response schema's title are each
    built from the endpoint function's name and its path, so two routes can
    only ever differ there. What is left — the parameters, the request body,
    the response shapes — is the comparison.
    """
    return {
        key: _documented(cast("dict[str, object]", value)) if isinstance(value, dict) else value
        for key, value in operation.items()
        if key not in DERIVED
    }


@pytest.fixture(autouse=True)
def _forget_the_last_request() -> None:
    SEEN.clear()


@pytest.mark.anyio
async def test_an_async_route_publishes_the_request_the_framework_serves() -> None:
    async with _serving(_application()) as client:
        response = await client.get("/served")

    assert response.status_code == 200
    assert SEEN["published"] is SEEN["request"]
    assert SEEN["built"] is SEEN["request"]


@pytest.mark.anyio
async def test_a_sync_route_publishes_the_request_the_framework_serves() -> None:
    async with _serving(_application()) as client:
        response = await client.get("/served-sync")

    assert response.status_code == 200
    assert SEEN["published"] is SEEN["request"]
    assert SEEN["built"] is SEEN["request"]


@pytest.mark.anyio
async def test_a_marked_route_still_resolves_the_service_it_asked_for() -> None:
    async with _serving(_application()) as client:
        response = await client.get("/served")

    assert response.json() == {"path": "/served"}


@pytest.mark.anyio
async def test_a_marked_route_still_fills_the_parameters_the_framework_owns() -> None:
    async with _serving(_application()) as client:
        response = await client.get("/marked/7", params={"q": "hi"})

    assert response.json() == {"item": 7, "q_length": 2}


def test_a_marked_routes_documented_operation_is_the_unmarked_ones() -> None:
    schema = _application().openapi()

    paths = cast("dict[str, dict[str, dict[str, object]]]", schema["paths"])
    marked = _documented(paths["/marked/{item_id}"]["get"])

    # The markers are the whole difference between the two signatures, so what
    # is left to compare must still be the two HTTP parameters, not a shell.
    parameters = cast("list[dict[str, object]]", marked["parameters"])
    assert [parameter["name"] for parameter in parameters] == ["item_id", "q"]
    assert marked == _documented(paths["/plain/{item_id}"]["get"])


@pytest.mark.anyio
async def test_a_socket_route_publishes_the_socket_the_framework_serves() -> None:
    sent = await _handshake(ScopePerRequest(_application()), "/socket")

    # The endpoint ran to its close, so what it recorded is this connection's.
    assert sent == ["websocket.accept", "websocket.close"]
    assert isinstance(SEEN["request"], WebSocket)
    assert SEEN["published"] is SEEN["request"]
    assert SEEN["built"] is SEEN["request"]


@pytest.mark.anyio
async def test_requests_served_at_once_each_read_the_connection_of_their_own() -> None:
    answered: dict[int, dict[str, str]] = {}

    async def drive(client: httpx.AsyncClient, token: int) -> None:
        response = await client.get(f"/concurrent/{token}")
        answered[token] = cast("dict[str, str]", response.json())

    async with (
        _serving(_application()) as client,
        anyio.create_task_group() as requests,
    ):
        for number in range(CONCURRENT):
            _ = requests.start_soon(drive, client, number)

    assert answered == {
        number: {"path": f"/concurrent/{number}", "token": str(number)}
        for number in range(CONCURRENT)
    }


@pytest.mark.anyio
async def test_a_task_the_framework_defers_still_reads_the_requests_connection() -> None:
    async with _serving(_application()) as client:
        response = await client.get("/deferred")

    # The response has gone out and the task ran after it, inside the scope.
    assert response.status_code == 200
    assert SEEN["deferred"] is SEEN["request"]
