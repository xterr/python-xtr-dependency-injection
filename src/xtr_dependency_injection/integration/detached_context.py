"""The context a new connection starts in: the server's, without an earlier request's work.

A server gives no promise about the context a connection's task starts with:
on a kept-alive socket it may be a copy of the previous request's, taken while
that request still had its unit of work open and its connection published.
Code that runs before the connection's own scope opens — middleware outside
the kernel's, a server's error handling — would then read and write that
request's scoped services. A server or an entry point serving each connection
in the context this returns hands every connection a clean start.

:func:`register_detached_variable` is how a library's bundle adds the context
variable it keeps per-request state in — held messages, a begun transaction,
a log unit — to what a new connection starts without.
"""

from __future__ import annotations

from contextvars import Context, copy_context

from xtr_dependency_injection.runtime._detached_variables import (
    detach_variables,
    register_detached_variable,
)

__all__ = ["detached_context", "register_detached_variable"]


def detached_context() -> Context:
    """Return a copy of the current context in which no earlier request's work is reachable.

    No unit of work is open in it and no connection is served, and every
    other context variable registered as per-request state is back at the
    value a new connection starts from. Everything else the context holds —
    a tracing span or an error-reporting scope an outer wrapper set — is kept.
    The current context itself is left as it is.
    """
    context = copy_context()
    context.run(detach_variables)
    return context
