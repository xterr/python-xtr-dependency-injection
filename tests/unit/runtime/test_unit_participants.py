"""Services told when every unit of work begins and ends."""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack

import pytest

from tests.fixtures import app_unit_participants
from tests.fixtures.app_unit_participants import JOURNAL, Resource
from xtr_dependency_injection import bind_callable, current_unit_of_work, unit_of_work
from xtr_dependency_injection.integration.wireup import create_container
from xtr_dependency_injection.runtime.wireup_container import WireupContainer

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def _journal() -> None:
    JOURNAL.clear()
    app_unit_participants.FAILING.clear()


def _container() -> WireupContainer:
    return WireupContainer(create_container([], scan=["tests.fixtures.app_unit_participants"]))


async def test_participants_see_every_unit_begin_and_end_in_order() -> None:
    container = _container()

    async with unit_of_work(container):
        JOURNAL.append("body")
    async with unit_of_work(container):
        pass

    assert JOURNAL == [
        "began first-1",
        "began second-1",
        "body",
        "ended second-1",
        "ended first-1",
        "began first-2",
        "began second-2",
        "ended second-2",
        "ended first-2",
    ]


async def test_joining_a_unit_calls_no_participant() -> None:
    container = _container()

    async with unit_of_work(container):
        JOURNAL.clear()
        async with unit_of_work(container):
            pass
        assert JOURNAL == []


async def test_a_unit_of_its_own_inside_another_begins_and_ends() -> None:
    container = _container()

    async with unit_of_work(container), unit_of_work(container, join=False):
        JOURNAL.append("inner")

    assert JOURNAL == [
        "began first-1",
        "began second-1",
        "began first-2",
        "began second-2",
        "inner",
        "ended second-2",
        "ended first-2",
        "ended second-1",
        "ended first-1",
    ]


async def test_a_call_bound_with_its_own_scope_is_a_unit_participants_see() -> None:
    container = _container()

    async def command() -> None:
        JOURNAL.append("command")

    _ = await bind_callable(container, command, per_call_scope=True)()

    assert JOURNAL == [
        "began first-1",
        "began second-1",
        "command",
        "ended second-1",
        "ended first-1",
    ]


async def test_a_failing_participant_still_closes_the_unit() -> None:
    container = _container()
    app_unit_participants.FAILING.add("Second.unit_ended")

    with pytest.raises(ExceptionGroup) as raised:
        async with unit_of_work(container) as unit:
            _ = await unit.get(Resource)

    assert [str(error) for error in raised.value.exceptions] == ["Second.unit_ended"]
    assert JOURNAL == ["began first-1", "began second-1", "teardown", "ended first-1"]
    assert current_unit_of_work() is None


async def test_participants_end_a_unit_exited_in_another_context() -> None:
    container = _container()
    stack = AsyncExitStack()

    async def open_it() -> None:
        _ = await stack.enter_async_context(unit_of_work(container))

    await asyncio.create_task(open_it())
    await asyncio.create_task(stack.aclose())

    assert JOURNAL == [
        "began first-1",
        "began second-1",
        "ended second-1",
        "ended first-1",
    ]


async def test_a_failing_unit_began_ends_the_ones_already_begun() -> None:
    container = _container()
    app_unit_participants.FAILING.add("Second.unit_began")

    with pytest.raises(ExceptionGroup) as raised:
        async with unit_of_work(container):
            JOURNAL.append("body")

    assert [str(error) for error in raised.value.exceptions] == ["Second.unit_began"]
    assert JOURNAL == ["began first-1", "ended first-1"]
    assert current_unit_of_work() is None


async def test_a_failing_unit_ended_is_a_note_on_the_bodys_exception() -> None:
    container = _container()
    app_unit_participants.FAILING.add("Second.unit_ended")

    with pytest.raises(LookupError) as raised:
        async with unit_of_work(container):
            raise LookupError

    assert raised.value.__notes__ == ["Second.unit_ended failed: RuntimeError('Second.unit_ended')"]
    assert JOURNAL == ["began first-1", "began second-1", "ended first-1"]


async def test_participants_of_an_unbooted_create_container_are_resolved_on_first_unit() -> None:
    container = _container()
    assert JOURNAL == []

    async with unit_of_work(container):
        pass

    assert JOURNAL[:2] == ["began first-1", "began second-1"]


async def test_participants_end_after_the_scope_teardown() -> None:
    container = _container()

    async with unit_of_work(container) as unit:
        _ = await unit.get(Resource)

    assert JOURNAL == [
        "began first-1",
        "began second-1",
        "teardown",
        "ended second-1",
        "ended first-1",
    ]
