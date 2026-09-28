"""The seam between a served application and a kernel, and the markers' resolvers.

:func:`attach` stores a compiled kernel's container on the application's
state; :func:`request_scope` opens the container scope one request's scoped
services live in; :func:`provider` derives the resolver a marker becomes.
Serving an application takes the HTTP kernel package on top: until its setup
call attaches a kernel, a resolver that runs can only say what is missing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from xtr_dependency_injection.exception import FastapiIntegrationError
from xtr_dependency_injection.integration._resolvers import (
    STATE_KEY,
    AttachedKernel,
    attached_kernel,
    provider,
    request_scope,
)
from xtr_dependency_injection.integration.wireup import engine_container
from xtr_dependency_injection.runtime.wireup_container import WireupContainer

if TYPE_CHECKING:
    from starlette.applications import Starlette

    from xtr_dependency_injection.kernel.compiled_kernel import CompiledKernel

__all__ = ["attach", "detach", "provider", "request_scope"]

_ALREADY_ATTACHED: Final = (
    "a kernel already serves this application: detach(app) before attaching another"
)


def attach(app: Starlette, compiled: CompiledKernel) -> None:
    """Serve ``app`` from ``compiled``'s container.

    Args:
        app: The application to serve.
        compiled: The kernel whose container the resolvers read.

    Raises:
        FastapiIntegrationError: If a kernel is already attached; call
            :func:`detach` first to swap it.
    """
    if attached_kernel(app) is not None:
        raise FastapiIntegrationError(_ALREADY_ATTACHED)
    engine = engine_container(compiled)
    # The kernel's public container is typed by the contract interface;
    # wrapping the same engine gives the resolvers the parameter and
    # environment access the contract does not carry.
    setattr(app.state, STATE_KEY, AttachedKernel(WireupContainer(engine), engine))


def detach(app: Starlette) -> None:
    """Stop serving ``app``; a no-op when no kernel is attached."""
    if attached_kernel(app) is not None:
        delattr(app.state, STATE_KEY)
