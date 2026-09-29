"""A unit of work: one scope shared by everything done for one message, job or task.

A scoped service — a database session, a per-task cache — is built once per
unit of work and released when the unit ends. Everything run inside it sees the
same instance: what the unit's owner asks for through the container it was
handed, and every call :func:`~xtr_dependency_injection.bind_callable` bound
without a scope of its own.

Units of one container do not nest: opening one while another is open on the
same container joins it, so work started from inside a unit — a message
dispatched while another is handled — shares its instances. Only new work —
a message a worker received — asks for one of its own inside. A unit of another
container — a second kernel in the process — is never joined: that container
opens one of its own, inside.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from xtr_dependency_injection.exception import InvalidArgumentTypeError

from ._unit_scope import current_unit, entered, open_unit
from .wireup_container import WireupContainer

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from contextlib import AbstractAsyncContextManager

    from xtr_service_contracts import ContainerInterface

__all__ = ["current_unit_of_work", "unit_of_work"]


def unit_of_work(
    container: ContainerInterface, *, join: bool = True
) -> AbstractAsyncContextManager[ContainerInterface]:
    """Open a unit of work on ``container``'s services — or join the one it has open.

    The returned container resolves scoped services as well as singletons:
    each scoped one is built on first use, shared by everything in the unit,
    and released when the unit that opened it exits — even when it raises,
    which the service's cleanup sees.

    ```python
    async with unit_of_work(container) as unit:
        session = await unit.get(AsyncSession)
    ```

    Args:
        container: Whose services the unit resolves.
        join: Join the unit ``container`` has open, if any. ``False`` opens
            one of its own inside it, for work that is new rather than part
            of what is under way — a message a worker received, say; the
            outer unit is back when it exits.

    Raises:
        InvalidArgumentTypeError: If ``container`` is not one a kernel built.
    """
    return _unit_of_work(container, join=join)


@asynccontextmanager
async def _unit_of_work(
    container: ContainerInterface, *, join: bool
) -> AsyncGenerator[ContainerInterface]:
    if not isinstance(container, WireupContainer):
        msg = "a unit of work needs a kernel-provided container"
        raise InvalidArgumentTypeError(msg)
    engine = container._engine()  # noqa: SLF001 — the unit owns the WireupContainer contract.  # pyright: ignore[reportPrivateUsage]
    opened = open_unit(engine) if join else None
    if opened is not None:
        yield WireupContainer(engine, opened)
        return
    async with engine.enter_scope() as scope:
        with entered(engine, scope):
            yield WireupContainer(engine, scope)


def current_unit_of_work() -> ContainerInterface | None:
    """Return the unit of work open in this context, or ``None`` outside one."""
    opened = current_unit()
    return None if opened is None else WireupContainer(*opened)
