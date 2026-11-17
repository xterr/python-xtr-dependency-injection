"""A unit of work: one scope shared by everything run for one request, message or command."""

from __future__ import annotations

import asyncio
import contextvars
import threading
from collections.abc import (
    AsyncIterator,  # noqa: TC003 — the engine reads the factory's return annotation
)
from contextlib import AsyncExitStack
from typing import TYPE_CHECKING, TypeVar, final

import anyio
import pytest
import wireup
from typing_extensions import override
from xtr_service_contracts import ContainerInterface

from tests.fixtures import app_hung_teardown, app_slow_scoped, app_unit_producer
from xtr_dependency_injection import (
    Injected,
    Kernel,
    bind_callable,
    current_unit_of_work,
    open_unit_of,
    unit_of_work,
)
from xtr_dependency_injection.compiler._registration import clone_function, synthesize_class_factory
from xtr_dependency_injection.exception import (
    InvalidArgumentTypeError,
    KernelShutDownError,
    UnitOfWorkClosedError,
)
from xtr_dependency_injection.integration.wireup import create_container
from xtr_dependency_injection.kernel import booted_kernel
from xtr_dependency_injection.runtime._unit_scope import units_drained
from xtr_dependency_injection.runtime.wireup_container import WireupContainer

if TYPE_CHECKING:
    from collections.abc import Hashable

T = TypeVar("T")

pytestmark = pytest.mark.anyio

_TIMEOUT = 5.0


@final
class Session:
    """A scoped service that records whether it was released."""

    def __init__(self) -> None:
        self.closed = False
        self.error: BaseException | None = None


async def session_factory() -> AsyncIterator[Session]:
    session = Session()
    try:
        yield session
    except BaseException as error:
        session.error = error
        raise
    finally:
        session.closed = True


def _container() -> WireupContainer:
    # wireup refuses to register one function twice; each container gets a clone, as the
    # compiler gives each kernel.
    engine = wireup.create_async_container(
        injectables=[wireup.injectable(clone_function(session_factory), lifetime="scoped")],
    )
    return WireupContainer(engine)


@final
class Counted:
    """A scoped service counting how often it is built."""

    built = 0

    def __init__(self) -> None:
        Counted.built += 1


def _counting_container() -> WireupContainer:
    Counted.built = 0
    engine = wireup.create_async_container(
        injectables=[wireup.injectable(synthesize_class_factory(Counted), lifetime="scoped")],
    )
    return WireupContainer(engine)


async def test_a_unit_builds_a_scoped_service_once_and_releases_it_at_the_end() -> None:
    container = _container()

    async with unit_of_work(container) as unit:
        first = await unit.get(Session)
        assert await unit.get(Session) is first
        assert not first.closed

    assert first.closed


async def test_each_unit_has_its_own_scoped_services() -> None:
    container = _container()

    async with unit_of_work(container) as unit:
        first = await unit.get(Session)
    async with unit_of_work(container) as unit:
        second = await unit.get(Session)

    assert first is not second


async def test_a_unit_opened_inside_another_joins_it() -> None:
    container = _container()

    async with unit_of_work(container) as outer:
        session = await outer.get(Session)
        async with unit_of_work(container) as inner:
            assert await inner.get(Session) is session
        assert not session.closed

    assert session.closed


async def test_a_unit_asked_not_to_join_is_one_of_its_own_inside_another() -> None:
    container = _container()

    async with unit_of_work(container) as outer:
        session = await outer.get(Session)
        async with unit_of_work(container, join=False) as inner:
            own = await inner.get(Session)
            assert own is not session
        assert own.closed
        assert await (await _current()).get(Session) is session

    assert session.closed


async def test_a_unit_of_another_container_is_not_joined() -> None:
    first, second = _container(), _container()

    async with unit_of_work(first) as outer:
        own = await outer.get(Session)
        async with unit_of_work(second) as inner:
            other = await inner.get(Session)
            assert other is not own
            assert current_unit_of_work() is not None
        assert other.closed
        assert not own.closed
        assert await (await _current()).get(Session) is own

    assert own.closed


async def test_a_unit_of_kernel_a_rejoins_across_a_unit_of_kernel_b() -> None:
    first, second = _container(), _container()

    async with unit_of_work(first) as outer:
        own = await outer.get(Session)
        async with unit_of_work(second), unit_of_work(first) as again:
            assert await again.get(Session) is own
        assert not own.closed

    assert own.closed


async def test_concurrent_first_resolutions_in_one_unit_build_one_instance() -> None:
    app_slow_scoped.GATE = app_slow_scoped.Gate()
    gate = app_slow_scoped.GATE
    container = WireupContainer(create_container([], scan=["tests.fixtures.app_slow_scoped"]))

    async with unit_of_work(container) as unit:
        first = asyncio.create_task(unit.get(app_slow_scoped.Slow))
        second = asyncio.create_task(unit.get(app_slow_scoped.Slow))
        _ = await gate.building.wait()
        gate.release.set()
        built = await asyncio.gather(first, second)

    assert gate.built == 1
    assert built[0] is built[1]


async def test_a_call_bound_on_another_container_does_not_join_the_unit() -> None:
    first, second = _container(), _container()
    received: list[Session] = []

    async def handler(session: Injected[Session]) -> None:
        received.append(session)

    bound = bind_callable(second, handler)
    async with unit_of_work(first) as unit:
        _ = await bound()
        own = await unit.get(Session)

    assert received[0] is not own
    assert received[0].closed


async def _current() -> ContainerInterface:
    unit = current_unit_of_work()
    assert unit is not None
    return unit


async def test_the_error_ending_a_unit_reaches_the_service_s_cleanup() -> None:
    container = _container()
    seen: list[Session] = []

    async def fail_inside_a_unit() -> None:
        async with unit_of_work(container) as unit:
            seen.append(await unit.get(Session))
            raise LookupError

    with pytest.raises(LookupError):
        await fail_inside_a_unit()

    assert seen[0].closed
    assert isinstance(seen[0].error, LookupError)


async def test_bound_callables_share_the_unit_they_are_called_in() -> None:
    container = _container()
    received: list[Session] = []

    async def handler(session: Injected[Session]) -> None:
        received.append(session)

    bound = bind_callable(container, handler)
    async with unit_of_work(container) as unit:
        _ = await bound()
        _ = await bound()
        own = await unit.get(Session)

    assert received[0] is received[1] is own


async def test_bound_callables_outside_a_unit_each_get_their_own() -> None:
    container = _container()
    received: list[Session] = []

    async def handler(session: Injected[Session]) -> None:
        received.append(session)

    bound = bind_callable(container, handler)
    _ = await bound()
    _ = await bound()

    assert received[0] is not received[1]
    assert all(session.closed for session in received)


async def test_a_call_bound_with_its_own_scope_keeps_it_inside_a_unit() -> None:
    container = _container()
    received: list[Session] = []

    async def command(session: Injected[Session]) -> None:
        received.append(session)

    bound = bind_callable(container, command, per_call_scope=True)
    async with unit_of_work(container) as unit:
        _ = await bound()
        own = await unit.get(Session)

    assert received[0] is not own
    assert received[0].closed


async def test_what_a_call_bound_with_its_own_scope_starts_joins_that_scope() -> None:
    container = _container()
    received: list[Session] = []

    async def handler(session: Injected[Session]) -> None:
        received.append(session)

    inner = bind_callable(container, handler)

    async def command(session: Injected[Session]) -> None:
        received.append(session)
        _ = await inner()

    _ = await bind_callable(container, command, per_call_scope=True)()

    assert received[0] is received[1]
    assert received[0].closed


async def test_there_is_no_unit_of_work_outside_one() -> None:
    container = _container()

    assert current_unit_of_work() is None
    async with unit_of_work(container):
        assert current_unit_of_work() is not None
    assert current_unit_of_work() is None


async def test_the_unit_reads_the_container_s_services_and_parameters() -> None:
    engine = wireup.create_async_container(
        injectables=[wireup.injectable(clone_function(session_factory), lifetime="scoped")],
        config={"app": {"name": "shop"}},
    )
    container = WireupContainer(engine)

    async with unit_of_work(container) as unit:
        assert unit.has(Session)
        assert unit.get_parameter("app.name") == "shop"
        assert unit.has_parameter("app")


async def test_a_unit_that_has_exited_is_gone_from_a_context_copied_inside_it() -> None:
    container = _container()

    async with unit_of_work(container):
        kept = contextvars.copy_context()

    assert kept.run(current_unit_of_work) is None


async def test_a_unit_exited_in_another_task_is_closed_for_every_context() -> None:
    container = _container()
    stack = AsyncExitStack()
    sessions: list[Session] = []
    copies: list[contextvars.Context] = []

    async def open_it() -> None:
        unit = await stack.enter_async_context(unit_of_work(container))
        sessions.append(await unit.get(Session))
        copies.append(contextvars.copy_context())

    await asyncio.create_task(open_it())
    await asyncio.create_task(stack.aclose())

    assert sessions[0].closed
    assert copies[0].run(current_unit_of_work) is None


async def test_a_child_task_outliving_its_unit_cannot_resolve_from_it() -> None:
    container = _counting_container()
    exited = asyncio.Event()

    async def later(unit: ContainerInterface) -> None:
        _ = await exited.wait()
        _ = await unit.get(Counted)

    async with unit_of_work(container) as unit:
        child = asyncio.create_task(later(unit))
    exited.set()

    with pytest.raises(UnitOfWorkClosedError):
        await child
    assert Counted.built == 0


async def test_current_unit_of_work_refuses_once_the_unit_closed() -> None:
    container = _counting_container()

    async with unit_of_work(container):
        kept = await _current()

    with pytest.raises(UnitOfWorkClosedError):
        _ = await kept.get(Counted)
    assert Counted.built == 0


async def test_a_joined_unit_refuses_once_the_unit_it_joined_closed() -> None:
    container = _counting_container()

    async with unit_of_work(container), unit_of_work(container) as joined:
        pass

    with pytest.raises(UnitOfWorkClosedError):
        _ = await joined.get(Counted)
    assert Counted.built == 0


async def test_a_unit_still_open_hands_out_its_shared_instance() -> None:
    container = _counting_container()

    async with unit_of_work(container) as unit:
        first = await unit.get(Counted)
        kept = await _current()

        assert await kept.get(Counted) is first


async def test_open_unit_of_finds_the_unit_open_on_the_containers_services() -> None:
    container = _counting_container()

    async with unit_of_work(container) as unit:
        opened = open_unit_of(container)
        assert opened is not None
        assert await opened.get(Counted) is await unit.get(Counted)

    assert open_unit_of(container) is None


async def test_open_unit_of_finds_no_unit_of_another_container() -> None:
    first, second = _counting_container(), _counting_container()

    async with unit_of_work(first):
        assert open_unit_of(second) is None


async def test_open_unit_of_refuses_a_container_no_kernel_built() -> None:
    with pytest.raises(InvalidArgumentTypeError, match="kernel-provided container"):
        _ = open_unit_of(_Foreign())


async def test_work_that_outlives_the_unit_it_started_in_opens_one_of_its_own() -> None:
    container = _container()
    exited = anyio.Event()
    first: list[Session] = []
    handed: list[tuple[Session, bool]] = []

    async def later() -> None:
        # Started inside the unit, so its context carries it; run once it is over.
        await exited.wait()
        async with unit_of_work(container) as unit:
            session = await unit.get(Session)
            handed.append((session, session.closed))

    async with anyio.create_task_group() as tasks:
        async with unit_of_work(container) as unit:
            first.append(await unit.get(Session))
            _ = tasks.start_soon(later)
        exited.set()

    # Joining the unit that exited would have handed out its released session.
    assert handed[0][0] is not first[0]
    assert handed[0][1] is False


async def test_a_container_no_kernel_built_is_refused() -> None:
    with pytest.raises(InvalidArgumentTypeError, match="kernel-provided container"):
        async with unit_of_work(_Foreign()):
            pass


def _hung_kernel() -> Kernel:
    app_hung_teardown.GATE = app_hung_teardown.Gate()
    return Kernel("tests.fixtures.app_hung_teardown", env="test", bundles={})


async def test_shutdown_waits_for_an_open_unit() -> None:
    booted = await _hung_kernel().boot()
    gate = app_hung_teardown.GATE
    held = asyncio.Event()
    journal: list[str] = []

    async def hold() -> None:
        async with unit_of_work(booted.container) as unit:
            _ = await unit.get(app_hung_teardown.Hung)
            _ = await held.wait()
        journal.append("unit closed")

    unit = asyncio.create_task(hold())
    await asyncio.sleep(0)
    shutdown = asyncio.create_task(booted.shutdown())
    for _turn in range(20):
        await asyncio.sleep(0)
    assert not shutdown.done()

    held.set()
    _ = await asyncio.wait_for(gate.closing.wait(), timeout=_TIMEOUT)
    assert not shutdown.done()
    gate.release.set()
    await asyncio.wait_for(shutdown, timeout=_TIMEOUT)
    journal.append("shut down")
    await unit

    assert gate.closed
    assert journal == ["unit closed", "shut down"]


async def test_shutdown_gives_up_after_the_drain_timeout(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(booted_kernel, "_SHUTDOWN_DRAIN_TIMEOUT", 0.05)
    booted = await _hung_kernel().boot()
    gate = app_hung_teardown.GATE

    async def hold() -> None:
        async with unit_of_work(booted.container) as unit:
            _ = await unit.get(app_hung_teardown.Hung)

    unit = asyncio.create_task(hold())
    _ = await asyncio.wait_for(gate.closing.wait(), timeout=_TIMEOUT)

    await asyncio.wait_for(booted.shutdown(), timeout=_TIMEOUT)

    assert not gate.closed
    assert [record.getMessage() for record in caplog.records] == [
        "shutting the kernel down with units of work still open"
    ]
    assert caplog.records[0].__dict__["open_units"] == 1
    gate.release.set()
    await unit


async def test_shutdown_with_no_unit_open_does_not_wait() -> None:
    booted = await _hung_kernel().boot()

    await asyncio.wait_for(booted.shutdown(), timeout=0.5)


async def test_shutdown_waits_for_units_once_its_hooks_stopped_their_producer(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app_unit_producer.PRODUCER = app_unit_producer.Producer()
    producer = app_unit_producer.PRODUCER
    kernel = Kernel("tests.fixtures.app_unit_producer", env="test", bundles={})
    booted = await kernel.boot()

    async def produce() -> None:
        async with unit_of_work(booted.container):
            _ = await producer.stop.wait()
        producer.journal.append("unit closed")

    running = asyncio.create_task(produce())
    await asyncio.sleep(0)

    await asyncio.wait_for(booted.shutdown(), timeout=1.0)
    producer.journal.append("shut down")
    await running

    assert producer.journal == ["asked to stop", "unit closed", "shut down"]
    assert caplog.records == []


async def test_resolving_after_shutdown_raises() -> None:
    booted = await _hung_kernel().boot()
    container = booted.container
    await booted.shutdown()

    with pytest.raises(KernelShutDownError, match="has shut down"):
        _ = await container.get(app_hung_teardown.Hung)


async def test_a_shutdown_cancelled_while_draining_still_closes_the_kernel() -> None:
    booted = await _hung_kernel().boot()
    held = asyncio.Event()
    entered = asyncio.Event()

    async def hold() -> None:
        async with unit_of_work(booted.container):
            entered.set()
            _ = await held.wait()

    unit = asyncio.create_task(hold())
    _ = await entered.wait()
    shutdown = asyncio.create_task(booted.shutdown())
    for _turn in range(20):
        await asyncio.sleep(0)
    _ = shutdown.cancel()

    with pytest.raises(asyncio.CancelledError):
        await shutdown
    with pytest.raises(KernelShutDownError):
        _ = await booted.container.get(app_hung_teardown.Hung)
    held.set()
    await unit


async def test_a_unit_closing_after_the_waiting_loop_closed_keeps_its_own_outcome() -> None:
    """A shutdown waiting on another thread's loop that was closed meanwhile is not woken."""
    container = _container()
    engine = container._engine()
    waiting = threading.Event()

    def wait_in_a_loop_that_is_then_closed() -> None:
        loop = asyncio.new_event_loop()
        drained = loop.create_task(units_drained(engine, _TIMEOUT))
        _ = loop.call_soon(waiting.set)
        loop.run_until_complete(asyncio.sleep(0.01))
        assert not drained.done()
        loop.close()

    async def use() -> None:
        async with unit_of_work(container):
            thread = threading.Thread(target=wait_in_a_loop_that_is_then_closed)
            thread.start()
            thread.join()
            msg = "the unit's own"
            raise LookupError(msg)

    with pytest.raises(LookupError, match="the unit's own"):
        await use()
    assert waiting.is_set()


@final
class _Foreign(ContainerInterface):
    @override
    async def get(self, service: type[T], /, qualifier: Hashable | None = None) -> T:
        raise LookupError(service, qualifier)

    @override
    def has(self, service: type[object], /, qualifier: Hashable | None = None) -> bool:
        del service, qualifier
        return False

    @override
    def get_parameter(self, name: str, /) -> object:
        raise LookupError(name)

    @override
    def has_parameter(self, name: str, /) -> bool:
        del name
        return False
