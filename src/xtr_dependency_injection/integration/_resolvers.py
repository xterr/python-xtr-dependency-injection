"""What a served request resolves against: the containers a kernel attached.

Kept apart from the seam module deliberately: the markers' base lazily
derives resolvers from :func:`provider`, so this module must never reach the
kernel machinery — it only reads what the seam's ``attach`` stored on the
application and what :func:`request_scope` parked on the connection.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Protocol, cast, final

# The framework resolves the resolvers' annotations at runtime, so the
# connection class must be importable when it does.
from starlette.requests import HTTPConnection  # noqa: TC002 — read at runtime
from wireup import AsyncContainer

from xtr_dependency_injection.exception import FastapiIntegrationError
from xtr_dependency_injection.runtime._unit_scope import entered

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Awaitable, Callable, Hashable
    from contextlib import AbstractAsyncContextManager
    from typing import Literal

    from starlette.applications import Starlette
    from starlette.types import Scope
    from wireup import ScopedAsyncContainer

__all__ = ["connection_of", "current_connection", "provider", "request_scope"]

NO_KERNEL: Final = (
    "this route asks the container for a dependency, but no kernel serves "
    "this application: call xtr_http_kernel.setup(app, kernel)"
)

NO_SCOPE: Final = (
    "this dependency needs the container, but no request scope is open: it can "
    "only be resolved while a request of an application wired with "
    "xtr_http_kernel.setup(app, kernel) is served"
)

NO_CONNECTION: Final = (
    "the current connection can only be read while a request is served and a "
    "marker of it has resolved: a command, a worker, or a route that declared "
    "no marker has none"
)

STATE_KEY: Final = "_xtr_dependency_injection"
"""Where the seam's ``attach`` stores the kernel on the application's state."""

SERVED_KEY: Final = "_xtr_dependency_injection_served"
"""Where :func:`request_scope` parks what it serves, on the connection's own scope.

The scope a server builds for one connection is the one thing that is that
connection's and no other's: the framework hands it to every resolver, and no
task holds another connection's by accident — whereas the context a task
starts with may be a copy of an earlier request's. So what a request is
resolved against is found there, never in what the running context carries.
"""


@final
class _Served:
    """What one request scope serves: its container scope, and the connection published in it.

    Every resolver publishes the connection the framework handed it, so the
    per-request factory of an integration package can read the framework's
    own request object — the container fills no request parameter of its
    own, because the framework fills those only for what it calls itself.

    Published by changing this record, never the context: a synchronous
    endpoint in a copied context and a task the request started read the one
    record, and nothing a resolver publishes outlives the scope. It is
    emptied when the scope exits, so a context that outlasts the request, or
    that another request was started from, reads nothing of it.
    """

    __slots__ = ("connection", "scoped")

    def __init__(self, scoped: ScopedAsyncContainer, connection: HTTPConnection | None) -> None:
        self.scoped: ScopedAsyncContainer | None = scoped
        self.connection = connection

    def close(self) -> None:
        """Forget the scope and the connection: the request is over."""
        self.scoped = None
        self.connection = None


_SERVED: Final[ContextVar[_Served | None]] = ContextVar("xtr_served_request", default=None)
"""What the request scope open in this context serves, bound by :func:`request_scope`.

Only for what has no connection in hand — a factory the container runs. It is
bound when the scope opens and set nowhere else, so what it answers is the
request whose scope is open here, not whatever the context held before.
"""

_PROVIDERS: Final[dict[tuple[str, object, object], Callable[..., Awaitable[object]]]] = {}


class KernelContainer(Protocol):
    """What the ``param`` and ``env`` resolvers need from the attached container."""

    def get_parameter_raw(self, name: str, /) -> object:
        """Return the parameter ``name`` as stored, placeholders included."""
        ...

    async def resolve_env_placeholders(self, value: object, /) -> object:
        """Return ``value`` with every environment placeholder resolved."""
        ...

    async def get_env(self, name: str, /) -> object:
        """Return the value of the environment variable expression ``name``."""
        ...


@final
@dataclass(frozen=True, slots=True)
class AttachedKernel:
    """What the seam's ``attach`` stores: one kernel's two faces of one container."""

    container: KernelContainer
    engine: AsyncContainer


def attached_kernel(app: Starlette) -> AttachedKernel | None:
    """Return what the seam's ``attach`` stored on ``app``, if anything."""
    attached: object = getattr(app.state, STATE_KEY, None)
    return attached if isinstance(attached, AttachedKernel) else None


def request_scope(app: Starlette, connection_scope: Scope) -> AbstractAsyncContextManager[None]:
    """Open the container scope the request ``connection_scope`` describes is served in.

    While the returned context is entered, the resolvers of this module
    resolve that connection's markers from the scope, and it is the unit of
    work what the request starts joins — a message it dispatches shares its
    scoped services. It closes — and the resolvers stop — when the context
    exits, even when the body raises.

    The request owns only what it opened. A server may start a request's task
    from the context of an earlier one, so nothing the calling context
    carries is taken for this request's: only a scope already open on this
    very connection encloses the new one, and the connection published in it
    stays readable inside.

    Args:
        app: The application whose attached kernel serves the request.
        connection_scope: The connection as the server described it.

    Raises:
        FastapiIntegrationError: On enter, if no kernel is attached to
            ``app``.
    """
    return _request_scope(app, connection_scope)


@asynccontextmanager
async def _request_scope(app: Starlette, connection_scope: Scope) -> AsyncGenerator[None, None]:
    attached = attached_kernel(app)
    if attached is None:
        raise FastapiIntegrationError(NO_KERNEL)
    # Read off the connection, not the context: only a scope opened on this
    # connection encloses this one.
    enclosing = _served_of(connection_scope)
    async with attached.engine.enter_scope() as scoped:
        served = _Served(scoped, enclosing.connection if enclosing is not None else None)
        connection_scope[SERVED_KEY] = served
        bound = _SERVED.set(served)
        try:
            with entered(attached.engine, scoped):
                yield
        finally:
            _SERVED.reset(bound)
            served.close()
            if enclosing is None:
                del connection_scope[SERVED_KEY]
            else:
                connection_scope[SERVED_KEY] = enclosing


def connection_of(connection_scope: Scope) -> HTTPConnection | None:
    """Return the connection a marker of the request ``connection_scope`` describes published.

    Part of the seam, for an integration that holds the connection's scope:
    what it reads is that request's by construction, whatever context it is
    called from — where :func:`current_connection` answers for the request
    whose scope is open in the calling context.

    Args:
        connection_scope: The connection as the server described it.

    Returns:
        The connection the framework serves that request from, or ``None``
        when no scope is open on it or no marker of it has resolved.
    """
    served = _served_of(connection_scope)
    return served.connection if served is not None else None


def current_connection() -> HTTPConnection:
    """Return the connection of the request being served, for an integration.

    Part of the seam, beside :func:`provider` and :func:`request_scope`:
    application code does not call this. It exists so the per-request factory
    of an integration package — xtr-http-kernel's request factory — can read
    the framework's own request object, the very one the framework serves the
    request from, carrying what has already been read off the wire: a body, a
    parsed form. Building the injected request from that object makes it share
    those reads instead of consuming the wire a second time. In a route, take
    the framework's ``request: Request``; for the request as a message, take
    a ``ServerRequestInterface`` parameter. An integration that holds the
    connection's scope reads :func:`connection_of` instead.

    On a WebSocket route the object is the ``WebSocket`` — the connection
    class a request and a socket share is what a resolver is handed, whichever
    is being served.

    It is readable from the moment a marker of the request resolved until the
    request's scope exits, and that outlasts the response: a background task
    the framework runs once the response has gone out still reads the
    connection of the request that queued it.

    Only something built for this request may read it — a
    ``lifetime="scoped"`` or transient service, or a factory of one. A
    singleton is built once for the application and would hold on to the
    connection of whichever request happened to build it.

    Returns:
        The connection the framework is serving this request from.

    Raises:
        FastapiIntegrationError: If no marker of a served request has
            resolved, so there is no connection to read.
    """
    served = _SERVED.get()
    connection = served.connection if served is not None else None
    if connection is None:
        raise FastapiIntegrationError(NO_CONNECTION)
    return connection


def provider(
    kind: Literal["service", "param", "env"],
    key: object,
    qualifier: Hashable | None = None,
) -> Callable[..., Awaitable[object]]:
    """Return the resolver for one injection — the same one every time.

    One callable per ``(kind, key, qualifier)``: the framework tells route
    dependencies apart by the callable it was handed, and two equal markers
    must carry the same resolver to stay equal and hashable. A ``service``
    resolver reads the scope :func:`request_scope` parked on the connection
    it is handed; a ``param`` or ``env`` resolver reads the container the
    seam's ``attach`` stored on the application the connection belongs to.
    """
    cache_key = (kind, key, qualifier)
    cached = _PROVIDERS.get(cache_key)
    if cached is not None:
        return cached

    label = key.__qualname__ if isinstance(key, type) else str(key)
    name = f"xtr_{kind}[{label}]"
    match kind:
        case "service":
            # For ``service`` the key is the class the framework handed the marker.
            resolve = _service_resolver(cast("type[object]", key), qualifier, name)
        case "param":
            resolve = _param_resolver(str(key), name)
        case "env":
            resolve = _env_resolver(str(key), name)
    # ``setdefault`` keeps one canonical resolver even if two threads raced here.
    return _PROVIDERS.setdefault(cache_key, resolve)


def _service_resolver(
    service: type[object], qualifier: Hashable | None, name: str
) -> Callable[[HTTPConnection], Awaitable[object]]:
    """Build the resolver of one service injection, named ``name``."""

    async def resolve(request: HTTPConnection) -> object:
        served = _served_of(request.scope)
        if served is None or served.scoped is None:
            raise FastapiIntegrationError(NO_SCOPE)
        served.connection = request
        return await served.scoped.get(service, qualifier)

    resolve.__name__ = name
    resolve.__qualname__ = name
    # ``set_dependency`` tells an already-derived resolver apart by this flag.
    resolve.__dict__["__xtr_provider__"] = True
    return resolve


def _param_resolver(param: str, name: str) -> Callable[[HTTPConnection], Awaitable[object]]:
    """Build the resolver of one parameter injection, named ``name``."""

    async def resolve(request: HTTPConnection) -> object:
        container = _connection_container(request)
        _publish(request)
        return await container.resolve_env_placeholders(container.get_parameter_raw(param))

    resolve.__name__ = name
    resolve.__qualname__ = name
    # ``set_dependency`` tells an already-derived resolver apart by this flag.
    resolve.__dict__["__xtr_provider__"] = True
    return resolve


def _env_resolver(expression: str, name: str) -> Callable[[HTTPConnection], Awaitable[object]]:
    """Build the resolver of one environment variable injection, named ``name``."""

    async def resolve(request: HTTPConnection) -> object:
        container = _connection_container(request)
        _publish(request)
        return await container.get_env(expression)

    resolve.__name__ = name
    resolve.__qualname__ = name
    # ``set_dependency`` tells an already-derived resolver apart by this flag.
    resolve.__dict__["__xtr_provider__"] = True
    return resolve


def _served_of(connection_scope: Scope) -> _Served | None:
    """Return what the request scope open on ``connection_scope`` serves, if one is open."""
    served: object = connection_scope.get(SERVED_KEY)
    return served if isinstance(served, _Served) and served.scoped is not None else None


def _publish(request: HTTPConnection) -> None:
    """Publish ``request`` in the scope open on its connection.

    Only once the resolver's own guards have passed: one that could not
    resolve served nothing, and must leave nothing behind for the next read.
    Without a scope open on the connection there is nothing to publish into,
    and nothing built for the request to read it.
    """
    served = _served_of(request.scope)
    if served is not None:
        served.connection = request


def _connection_container(request: HTTPConnection) -> KernelContainer:
    """Return the container attached to the application ``request`` belongs to."""
    app = cast("Starlette", request.app)  # the framework types the connection's app loosely
    attached = attached_kernel(app)
    if attached is None:
        raise FastapiIntegrationError(NO_KERNEL)
    return attached.container
