"""Closing a unit's scope: every service torn down, however the unit is left."""

from __future__ import annotations

import asyncio
import gc
import logging
import weakref
from collections.abc import (
    AsyncIterator,  # noqa: TC003 — the engine reads the factories' return annotations
)
from contextvars import ContextVar
from typing import TYPE_CHECKING, final, override

import anyio
import pytest
import wireup

from xtr_dependency_injection import unit_of_work
from xtr_dependency_injection.exception import ScopeTeardownTimeoutError
from xtr_dependency_injection.runtime import _scope_exit
from xtr_dependency_injection.runtime.wireup_container import WireupContainer

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator

pytestmark = pytest.mark.anyio

_VALUE: ContextVar[str] = ContextVar("test_scope_exit_value", default="caller")


@final
class First:
    """Built first, so torn down last."""


@final
class Second:
    """Built second, so torn down first."""


def _container(*factories: Callable[..., object]) -> WireupContainer:
    return WireupContainer(
        wireup.create_async_container(
            injectables=[wireup.injectable(factory, lifetime="scoped") for factory in factories],
        )
    )


@final
class _Gate:
    """A teardown that says it started, then waits to be let go."""

    def __init__(self) -> None:
        self.tearing = asyncio.Event()
        self.release = asyncio.Event()
        self.closed: list[str] = []


def _services(gate: _Gate) -> WireupContainer:
    async def first() -> AsyncIterator[First]:
        yield First()
        gate.closed.append("First")

    async def second() -> AsyncIterator[Second]:
        yield Second()
        gate.tearing.set()
        _ = await gate.release.wait()
        gate.closed.append("Second")

    return _container(first, second)


async def _use_both(container: WireupContainer) -> None:
    async with unit_of_work(container) as unit:
        _ = await unit.get(First)
        _ = await unit.get(Second)


async def test_task_cancel_during_teardown_still_closes_every_scoped_service() -> None:
    gate = _Gate()
    task = asyncio.create_task(_use_both(_services(gate)))
    _ = await gate.tearing.wait()

    _ = task.cancel()
    await asyncio.sleep(0)
    gate.release.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert gate.closed == ["Second", "First"]


async def test_cancellation_is_raised_again_after_teardown() -> None:
    gate = _Gate()
    task = asyncio.create_task(_use_both(_services(gate)))
    _ = await gate.tearing.wait()

    _ = task.cancel()
    await asyncio.sleep(0)
    gate.release.set()
    _ = await asyncio.gather(task, return_exceptions=True)

    assert task.cancelled()


async def test_an_anyio_cancel_scope_does_not_skip_teardown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gate = _Gate()
    wait = asyncio.wait
    waits: list[None] = []

    async def counting(
        tasks: Iterable[asyncio.Future[object]],
    ) -> tuple[set[asyncio.Future[object]], set[asyncio.Future[object]]]:
        waits.append(None)
        return await wait(tasks)

    monkeypatch.setattr(asyncio, "wait", counting)
    container = _services(gate)
    scopes: list[anyio.CancelScope] = []

    async def inside_a_cancel_scope() -> None:
        with anyio.CancelScope() as scope:
            scopes.append(scope)
            await _use_both(container)

    task = asyncio.create_task(inside_a_cancel_scope())
    _ = await gate.tearing.wait()

    scopes[0].cancel()
    await asyncio.sleep(0)
    gate.release.set()
    await task

    assert gate.closed == ["Second", "First"]
    assert scopes[0].cancelled_caught
    assert len(waits) < 10_000


async def test_a_teardown_error_keeps_the_exception_being_unwound() -> None:
    async def failing() -> AsyncIterator[First]:
        try:
            yield First()
        finally:
            raise RuntimeError("close failed")

    container = _container(failing)

    async def fail_inside() -> None:
        async with unit_of_work(container) as unit:
            _ = await unit.get(First)
            raise LookupError

    with pytest.raises(LookupError) as raised:
        await fail_inside()

    assert raised.value.__notes__ == [
        "closing the unit's services also failed: RuntimeError('close failed')"
    ]


async def test_a_teardown_error_without_an_exception_being_unwound_is_raised() -> None:
    async def failing() -> AsyncIterator[First]:
        yield First()
        raise RuntimeError("close failed")

    container = _container(failing)

    async def use() -> None:
        async with unit_of_work(container) as unit:
            _ = await unit.get(First)

    with pytest.raises(ExceptionGroup) as raised:
        await use()

    # The container's own group, not the engine's error type.
    assert type(raised.value) is ExceptionGroup
    assert [str(error) for error in raised.value.exceptions] == ["close failed"]


async def test_cancellation_wins_over_a_teardown_error_and_keeps_it_as_a_note() -> None:
    tearing, release = asyncio.Event(), asyncio.Event()

    async def failing() -> AsyncIterator[First]:
        yield First()
        tearing.set()
        _ = await release.wait()
        raise RuntimeError("close failed")

    container = _container(failing)

    async def use() -> None:
        async with unit_of_work(container) as unit:
            _ = await unit.get(First)

    task = asyncio.create_task(use())
    _ = await tearing.wait()
    _ = task.cancel()
    await asyncio.sleep(0)
    release.set()

    with pytest.raises(asyncio.CancelledError) as raised:
        await task
    assert raised.value.__notes__ == ["raised while finishing: RuntimeError('close failed')"]


async def test_a_hung_teardown_raises_scope_teardown_timeout_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_scope_exit, "_TEARDOWN_TIMEOUT", 0.05)

    async def hung() -> AsyncIterator[First]:
        yield First()
        _ = await asyncio.Event().wait()

    container = _container(hung)

    async def use() -> None:
        async with unit_of_work(container) as unit:
            _ = await unit.get(First)

    with pytest.raises(ScopeTeardownTimeoutError, match=r"0\.05 seconds"):
        await use()


async def test_a_cancelled_unit_whose_teardown_hangs_stays_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_scope_exit, "_TEARDOWN_TIMEOUT", 0.05)
    entered = asyncio.Event()

    async def hung() -> AsyncIterator[First]:
        try:
            yield First()
        finally:
            _ = await asyncio.Event().wait()

    container = _container(hung)

    async def use() -> None:
        async with unit_of_work(container) as unit:
            _ = await unit.get(First)
            entered.set()
            _ = await asyncio.Event().wait()

    task = asyncio.create_task(use())
    _ = await entered.wait()
    _ = task.cancel()
    with pytest.raises(asyncio.CancelledError) as raised:
        await task

    assert task.cancelled()
    assert raised.value.__notes__ == [
        "closing the unit's services did not finish within 0.05 seconds"
    ]


async def test_a_failing_unit_whose_teardown_hangs_keeps_its_own_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_scope_exit, "_TEARDOWN_TIMEOUT", 0.05)

    async def hung() -> AsyncIterator[First]:
        try:
            yield First()
        finally:
            _ = await asyncio.Event().wait()

    container = _container(hung)

    async def use() -> None:
        async with unit_of_work(container) as unit:
            _ = await unit.get(First)
            msg = "the unit's own failure"
            raise LookupError(msg)

    with pytest.raises(LookupError, match="the unit's own failure") as raised:
        await use()
    assert raised.value.__notes__ == [
        "closing the unit's services did not finish within 0.05 seconds"
    ]


@pytest.fixture
def _no_cyclic_collection() -> Iterator[None]:
    gc.disable()
    try:
        yield
    finally:
        gc.enable()


@pytest.mark.usefixtures("_no_cyclic_collection")
async def test_a_scoped_instance_is_released_when_its_unit_exits() -> None:
    async def first() -> AsyncIterator[First]:
        yield First()

    container = _container(first)

    async with unit_of_work(container) as unit:
        kept = weakref.ref(await unit.get(First))
        assert kept() is not None
    del unit

    assert kept() is None


async def test_a_teardown_setting_a_context_variable_does_not_fail_the_scope() -> None:
    async def first() -> AsyncIterator[First]:
        yield First()
        _ = _VALUE.set("teardown")

    container = _container(first)

    async with unit_of_work(container) as unit:
        _ = await unit.get(First)

    assert _VALUE.get() == "caller"


def _close_warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [
        record
        for record in caplog.records
        if record.name == "xtr_dependency_injection" and record.levelno == logging.WARNING
    ]


async def test_a_failed_teardown_under_an_error_is_logged_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # A note on the unit's error reaches only whoever reports that error; an
    # application log written before the unit closed never sees it.
    async def failing() -> AsyncIterator[First]:
        try:
            yield First()
        finally:
            raise RuntimeError("close failed")

    container = _container(failing)

    async def fail_inside() -> None:
        async with unit_of_work(container) as unit:
            _ = await unit.get(First)
            raise LookupError

    with (
        caplog.at_level(logging.WARNING, logger="xtr_dependency_injection"),
        pytest.raises(LookupError),
    ):
        await fail_inside()

    (record,) = _close_warnings(caplog)
    assert "RuntimeError('close failed')" in record.getMessage()


async def test_a_failed_teardown_raised_bare_is_logged_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def failing() -> AsyncIterator[First]:
        yield First()
        raise RuntimeError("close failed")

    container = _container(failing)

    async def use() -> None:
        async with unit_of_work(container) as unit:
            _ = await unit.get(First)

    with (
        caplog.at_level(logging.WARNING, logger="xtr_dependency_injection"),
        pytest.raises(ExceptionGroup),
    ):
        await use()

    (record,) = _close_warnings(caplog)
    assert "RuntimeError('close failed')" in record.getMessage()


async def test_a_failed_teardown_of_a_cancelled_unit_is_logged_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    tearing, release = asyncio.Event(), asyncio.Event()

    async def failing() -> AsyncIterator[First]:
        yield First()
        tearing.set()
        _ = await release.wait()
        raise RuntimeError("close failed")

    container = _container(failing)

    async def use() -> None:
        async with unit_of_work(container) as unit:
            _ = await unit.get(First)

    with caplog.at_level(logging.WARNING, logger="xtr_dependency_injection"):
        task = asyncio.create_task(use())
        _ = await tearing.wait()
        _ = task.cancel()
        await asyncio.sleep(0)
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    (record,) = _close_warnings(caplog)
    assert "RuntimeError('close failed')" in record.getMessage()


async def test_a_hung_teardown_is_logged_once(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_scope_exit, "_TEARDOWN_TIMEOUT", 0.05)

    async def hung() -> AsyncIterator[First]:
        yield First()
        _ = await asyncio.Event().wait()

    container = _container(hung)

    async def use() -> None:
        async with unit_of_work(container) as unit:
            _ = await unit.get(First)

    with (
        caplog.at_level(logging.WARNING, logger="xtr_dependency_injection"),
        pytest.raises(ScopeTeardownTimeoutError),
    ):
        await use()

    (record,) = _close_warnings(caplog)
    assert "0.05 seconds" in record.getMessage()


async def test_a_clean_teardown_logs_nothing(caplog: pytest.LogCaptureFixture) -> None:
    async def fine() -> AsyncIterator[First]:
        yield First()

    container = _container(fine)

    with caplog.at_level(logging.DEBUG, logger="xtr_dependency_injection"):
        async with unit_of_work(container) as unit:
            _ = await unit.get(First)

    assert _close_warnings(caplog) == []


async def test_an_unreprable_teardown_failure_is_logged_by_its_class(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class ReprlessError(Exception):
        @override
        def __repr__(self) -> str:
            raise ValueError("cannot say")

    async def failing() -> AsyncIterator[First]:
        try:
            yield First()
        finally:
            raise ReprlessError

    container = _container(failing)

    async def fail_inside() -> None:
        async with unit_of_work(container) as unit:
            _ = await unit.get(First)
            raise LookupError

    with (
        caplog.at_level(logging.WARNING, logger="xtr_dependency_injection"),
        pytest.raises(LookupError),
    ):
        await fail_inside()

    (record,) = _close_warnings(caplog)
    assert "[unprintable " in record.getMessage()
    assert "ReprlessError]" in record.getMessage()
