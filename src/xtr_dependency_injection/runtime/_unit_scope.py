"""Where the unit of work open in this context is kept.

Kept apart from the public :mod:`~xtr_dependency_injection.runtime.unit_of_work`
so the engine glue — :func:`~xtr_dependency_injection.bind_callable` — can
read it without importing the container wrapper the public API hands out.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING, final

if TYPE_CHECKING:
    from collections.abc import Generator

    from wireup import AsyncContainer, ScopedAsyncContainer

__all__ = ["current_unit", "entered", "open_unit"]


@final
class _Unit:
    """One unit of work: the engine it was opened on, and its scope until it exits.

    A context copied while the unit is open — a task it started, a request a
    server began from an earlier one's context — keeps pointing at it after it
    is over. The scope is dropped at the exit so such a context finds no unit
    there, rather than one whose scoped services have been released.
    """

    __slots__ = ("engine", "scope")

    def __init__(self, engine: AsyncContainer, scope: ScopedAsyncContainer) -> None:
        self.engine = engine
        self.scope: ScopedAsyncContainer | None = scope


# The unit of work this context was last handed; open for as long as it holds a scope.
_current: ContextVar[_Unit | None] = ContextVar(
    "xtr_dependency_injection_unit_of_work", default=None
)


def current_unit() -> tuple[AsyncContainer, ScopedAsyncContainer] | None:
    """Return the engine and scope of the unit of work open in this context, if any."""
    unit = _current.get()
    if unit is None or unit.scope is None:
        return None
    return unit.engine, unit.scope


def open_unit(engine: AsyncContainer) -> ScopedAsyncContainer | None:
    """Return the scope of the unit of work open in this context on ``engine``, if any.

    A unit another engine opened — a second kernel's — is not ``engine``'s to join.
    """
    opened = current_unit()
    return opened[1] if opened is not None and opened[0] is engine else None


@contextmanager
def entered(engine: AsyncContainer, scope: ScopedAsyncContainer) -> Generator[None]:
    """Make ``scope`` of ``engine`` this context's unit of work until the block exits."""
    unit = _Unit(engine, scope)
    token = _current.set(unit)
    try:
        yield
    finally:
        _current.reset(token)
        unit.scope = None
