"""The context variables a new connection starts without, and the value each starts from.

A server may start a connection's task from a copy of an earlier connection's
context, taken mid-request. What that request opened — its unit of work, the
connection it serves, the messages it holds back, its log unit — must not
reach the new one, whatever the server copied; everything else the context
holds, a tracing span an outer wrapper set, must. So each module holding
per-request state in a context variable registers it here, and a new
connection starts in a copy of its context with every registered variable set
back.
"""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from xtr_dependency_injection.exception import DetachedVariableConflictError

if TYPE_CHECKING:
    from collections.abc import Callable
    from contextvars import ContextVar

__all__ = ["detach_variables", "register_detached_variable"]


# Each registered variable, the value it starts from, and what sets it back to that value.
_DETACHED: dict[object, tuple[object, Callable[[], object]]] = {}


def register_detached_variable[T](var: ContextVar[T], value: T) -> None:
    """Have every new connection start with ``var`` set to ``value``.

    A bundle registers the variables its library keeps per-request state in
    as the container is built, before the first connection is served. Every
    kernel in a process shares the registry: registering a variable again
    with the value it has is a no-op.

    Raises:
        DetachedVariableConflictError: If ``var`` is registered with another value.
    """
    registered = _DETACHED.get(var)
    if registered is not None:
        if registered[0] != value:
            raise DetachedVariableConflictError(var.name, registered[0], value)
        return
    _DETACHED[var] = (value, partial(var.set, value))


def detach_variables() -> None:
    """Set every registered variable back to the value a new connection starts from, here."""
    for _, detach in tuple(_DETACHED.values()):
        _ = detach()
