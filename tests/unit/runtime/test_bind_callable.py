"""A bound call's own scope, however the call is driven."""

from __future__ import annotations

import asyncio
import contextvars
import inspect
import types
from collections.abc import (
    AsyncIterator,  # noqa: TC003 — the engine reads the factory's return annotation
)
from typing import TYPE_CHECKING, cast, final

import pytest
import wireup

from tests.fixtures.app_unit_participants import JOURNAL
from xtr_dependency_injection import Injected, bind_callable, current_unit_of_work, unit_of_work
from xtr_dependency_injection.exception import UnitOfWorkClosedError
from xtr_dependency_injection.integration.wireup import create_container
from xtr_dependency_injection.runtime.wireup_container import WireupContainer

if TYPE_CHECKING:
    from collections.abc import Coroutine, Generator

pytestmark = pytest.mark.anyio


@final
class Session:
    """A scoped service that records whether it was released."""

    def __init__(self) -> None:
        self.closed = False


async def session_factory() -> AsyncIterator[Session]:
    session = Session()
    try:
        yield session
    finally:
        session.closed = True


def _container() -> WireupContainer:
    engine = wireup.create_async_container(
        injectables=[wireup.injectable(session_factory, lifetime="scoped")],
    )
    return WireupContainer(engine)


@types.coroutine
def _suspend() -> Generator[None]:
    """Hand control back to whoever steps the coroutine, as an awaited I/O would."""
    yield


async def _finish_in(context: contextvars.Context, call: Coroutine[object, object, object]) -> None:
    """Step ``call`` to its end in ``context``, waiting on what it waits on, as a task would."""
    while True:
        try:
            waited = context.run(call.send, None)
        except StopIteration:
            return
        if isinstance(waited, asyncio.Future):
            # What a coroutine yields to its task is a future of a result it never reads here.
            _ = await asyncio.wait((cast("asyncio.Future[object]", waited),))


@final
class Slow:
    """A scoped service whose factory takes its time."""


@final
class Handler:
    """A scoped handler class, counting how often it is built."""

    built = 0

    def __init__(self) -> None:
        Handler.built += 1

    async def __call__(self, slow: Injected[Slow]) -> None:
        del slow


async def test_a_per_call_scope_exited_in_another_context_does_not_raise() -> None:
    received: list[Session] = []

    async def command(session: Injected[Session]) -> None:
        received.append(session)
        await _suspend()

    call = bind_callable(_container(), command, per_call_scope=True)()
    assert inspect.iscoroutine(call)
    # Started in one context and finished in another, as a coroutine handed
    # between tasks is.
    contextvars.copy_context().run(call.send, None)
    await _finish_in(contextvars.copy_context(), call)

    assert received[0].closed


async def test_a_joined_call_whose_unit_closed_meanwhile_raises() -> None:
    building = asyncio.Event()
    release = asyncio.Event()

    async def slow_factory() -> Slow:
        building.set()
        _ = await release.wait()
        return Slow()

    Handler.built = 0
    container = WireupContainer(
        wireup.create_async_container(
            injectables=[
                wireup.injectable(slow_factory, lifetime="scoped"),
                wireup.injectable(Handler, lifetime="scoped"),
            ],
        )
    )
    bound = bind_callable(container, Handler)

    async def call_it() -> None:
        _ = await bound()

    async with unit_of_work(container):
        call = asyncio.create_task(call_it())
        _ = await building.wait()
    release.set()

    with pytest.raises(UnitOfWorkClosedError):
        await call
    assert Handler.built == 0


async def test_a_per_call_scope_finishes_its_teardown_when_cancelled() -> None:
    tearing, release = asyncio.Event(), asyncio.Event()
    closed: list[str] = []

    async def session() -> AsyncIterator[Session]:
        yield Session()
        tearing.set()
        _ = await release.wait()
        closed.append("session")

    async def slow() -> AsyncIterator[Slow]:
        yield Slow()
        closed.append("slow")

    container = WireupContainer(
        wireup.create_async_container(
            injectables=[
                wireup.injectable(slow, lifetime="scoped"),
                wireup.injectable(session, lifetime="scoped"),
            ],
        )
    )

    async def command(first: Injected[Slow], second: Injected[Session]) -> None:
        del first, second

    bound = bind_callable(container, command, per_call_scope=True)

    async def call_it() -> None:
        _ = await bound()

    task = asyncio.create_task(call_it())
    _ = await tearing.wait()
    _ = task.cancel()
    await asyncio.sleep(0)
    release.set()
    _ = await asyncio.gather(task, return_exceptions=True)

    assert task.cancelled()
    assert closed == ["session", "slow"]


async def test_a_call_outside_a_unit_runs_in_a_unit_of_its_own() -> None:
    JOURNAL.clear()
    container = WireupContainer(create_container([], scan=["tests.fixtures.app_unit_participants"]))
    inside: list[bool] = []

    async def handler() -> None:
        inside.append(current_unit_of_work() is not None)

    _ = await bind_callable(container, handler)()

    assert inside == [True]
    assert JOURNAL == ["began first-1", "began second-1", "ended second-1", "ended first-1"]
