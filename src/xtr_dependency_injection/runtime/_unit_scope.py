"""Where the unit of work open in this context is kept.

Kept apart from the public :mod:`~xtr_dependency_injection.runtime.unit_of_work`
so the engine glue — :func:`~xtr_dependency_injection.bind_callable` — can
read it without importing the container wrapper the public API hands out.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Generator

    from wireup import AsyncContainer, ScopedAsyncContainer

__all__ = ["current_unit", "entered", "open_unit"]

# The unit of work open in this context: the engine it was opened on, and its scope.
_current: ContextVar[tuple[AsyncContainer, ScopedAsyncContainer]] = ContextVar(
    "xtr_dependency_injection_unit_of_work"
)


def current_unit() -> tuple[AsyncContainer, ScopedAsyncContainer] | None:
    """Return the engine and scope of the unit of work open in this context, if any."""
    return _current.get(None)


def open_unit(engine: AsyncContainer) -> ScopedAsyncContainer | None:
    """Return the scope of the unit of work open in this context on ``engine``, if any.

    A unit another engine opened — a second kernel's — is not ``engine``'s to join.
    """
    opened = _current.get(None)
    return opened[1] if opened is not None and opened[0] is engine else None


@contextmanager
def entered(engine: AsyncContainer, scope: ScopedAsyncContainer) -> Generator[None]:
    """Make ``scope`` of ``engine`` this context's unit of work until the block exits."""
    token = _current.set((engine, scope))
    try:
        yield
    finally:
        _current.reset(token)
