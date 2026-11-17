"""Work finished whatever cancels the one waiting for it, within a deadline."""

from __future__ import annotations

import asyncio
from contextvars import ContextVar

import pytest

from xtr_dependency_injection.runtime import shielded

pytestmark = pytest.mark.anyio

_SEEN: ContextVar[str] = ContextVar("test_shielded_seen", default="none")


async def test_it_returns_what_the_work_returns() -> None:
    async def work() -> str:
        return "done"

    assert await shielded(work(), timeout=1.0) == "done"


async def test_it_raises_what_the_work_raises() -> None:
    async def work() -> None:
        raise LookupError

    with pytest.raises(LookupError):
        await shielded(work(), timeout=1.0)


async def test_cancelling_the_caller_lets_the_work_finish_then_cancels_it() -> None:
    started, release = asyncio.Event(), asyncio.Event()
    finished: list[bool] = []

    async def work() -> None:
        started.set()
        _ = await release.wait()
        finished.append(True)

    waiting = asyncio.create_task(shielded(work(), timeout=1.0))
    _ = await started.wait()
    _ = waiting.cancel("stopped by the test")
    await asyncio.sleep(0)
    release.set()

    with pytest.raises(asyncio.CancelledError) as raised:
        await waiting
    assert finished == [True]
    assert raised.value.args == ("stopped by the test",)


async def test_a_failure_while_the_caller_was_cancelled_is_a_note_on_the_cancellation() -> None:
    started, release = asyncio.Event(), asyncio.Event()

    async def work() -> None:
        started.set()
        _ = await release.wait()
        raise LookupError("lost")

    waiting = asyncio.create_task(shielded(work(), timeout=1.0))
    _ = await started.wait()
    _ = waiting.cancel()
    await asyncio.sleep(0)
    release.set()

    with pytest.raises(asyncio.CancelledError) as raised:
        await waiting
    assert raised.value.__notes__ == ["raised while finishing: LookupError('lost')"]


async def test_work_past_its_deadline_raises_timeout_error() -> None:
    async def work() -> None:
        _ = await asyncio.Event().wait()

    with pytest.raises(TimeoutError):
        await shielded(work(), timeout=0.05)


async def test_the_work_runs_in_a_copy_of_the_callers_context() -> None:
    _ = _SEEN.set("caller")

    async def work() -> str:
        value = _SEEN.get()
        _ = _SEEN.set("work")
        return value

    assert await shielded(work(), timeout=1.0) == "caller"
    assert _SEEN.get() == "caller"
