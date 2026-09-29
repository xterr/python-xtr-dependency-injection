"""What a served request resolves against: the containers a kernel attached.

Kept apart from the seam module deliberately: the markers' base lazily
derives resolvers from :func:`provider`, so this module must never reach the
kernel machinery — it only reads what the seam's ``attach`` stored on the
application and enters the scope :func:`request_scope` opens.
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
    from wireup import ScopedAsyncContainer

__all__ = ["provider", "request_scope"]

NO_KERNEL: Final = (
    "this route asks the container for a dependency, but no kernel serves "
    "this application: call xtr_http_kernel.setup(app, kernel)"
)

NO_SCOPE: Final = (
    "this dependency needs the container, but no request scope is open: it can "
    "only be resolved while a request of an application wired with "
    "xtr_http_kernel.setup(app, kernel) is served"
)

STATE_KEY: Final = "_xtr_dependency_injection"
"""Where the seam's ``attach`` stores the kernel on the application's state."""

_SCOPED: Final[ContextVar[ScopedAsyncContainer | None]] = ContextVar(
    "xtr_request_scope", default=None
)
"""The scope of the request being served, set by :func:`request_scope`."""

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


def request_scope(app: Starlette) -> AbstractAsyncContextManager[None]:
    """Open the container scope one request's scoped services live in.

    While the returned context is entered, the ``service`` resolvers of this
    module resolve from the scope, and it is the unit of work what the request
    starts joins — a message it dispatches shares its scoped services. It
    closes — and the resolvers stop — when the context exits, even when the
    body raises.

    Raises:
        FastapiIntegrationError: On enter, if no kernel is attached to
            ``app``.
    """
    return _request_scope(app)


@asynccontextmanager
async def _request_scope(app: Starlette) -> AsyncGenerator[None, None]:
    attached = attached_kernel(app)
    if attached is None:
        raise FastapiIntegrationError(NO_KERNEL)
    async with attached.engine.enter_scope() as scoped:
        token = _SCOPED.set(scoped)
        try:
            with entered(attached.engine, scoped):
                yield
        finally:
            _SCOPED.reset(token)


def provider(
    kind: Literal["service", "param", "env"],
    key: object,
    qualifier: Hashable | None = None,
) -> Callable[..., Awaitable[object]]:
    """Return the resolver for one injection — the same one every time.

    One callable per ``(kind, key, qualifier)``: the framework tells route
    dependencies apart by the callable it was handed, and two equal markers
    must carry the same resolver to stay equal and hashable. A ``service``
    resolver reads the scope :func:`request_scope` opened; a ``param`` or
    ``env`` resolver reads the container the seam's ``attach`` stored on the
    application the connection belongs to.
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
) -> Callable[[], Awaitable[object]]:
    """Build the resolver of one service injection, named ``name``."""

    async def resolve() -> object:
        scoped = _SCOPED.get()
        if scoped is None:
            raise FastapiIntegrationError(NO_SCOPE)
        return await scoped.get(service, qualifier)

    resolve.__name__ = name
    resolve.__qualname__ = name
    # ``set_dependency`` tells an already-derived resolver apart by this flag.
    resolve.__dict__["__xtr_provider__"] = True
    return resolve


def _param_resolver(param: str, name: str) -> Callable[[HTTPConnection], Awaitable[object]]:
    """Build the resolver of one parameter injection, named ``name``."""

    async def resolve(request: HTTPConnection) -> object:
        container = _connection_container(request)
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
        return await container.get_env(expression)

    resolve.__name__ = name
    resolve.__qualname__ = name
    # ``set_dependency`` tells an already-derived resolver apart by this flag.
    resolve.__dict__["__xtr_provider__"] = True
    return resolve


def _connection_container(request: HTTPConnection) -> KernelContainer:
    """Return the container attached to the application ``request`` belongs to."""
    app = cast("Starlette", request.app)  # the framework types the connection's app loosely
    attached = attached_kernel(app)
    if attached is None:
        raise FastapiIntegrationError(NO_KERNEL)
    return attached.container
