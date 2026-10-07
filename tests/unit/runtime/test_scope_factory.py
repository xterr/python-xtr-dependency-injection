"""``ScopeFactory`` opens a unit of work on its container without exposing it."""

from __future__ import annotations

from collections.abc import (
    AsyncIterator,  # noqa: TC003 — the engine reads the factory's return annotation
)
from typing import final

import pytest
import wireup

from xtr_dependency_injection import current_unit_of_work
from xtr_dependency_injection.runtime.scope_factory import ScopeFactory
from xtr_dependency_injection.runtime.scope_factory_interface import ScopeFactoryInterface
from xtr_dependency_injection.runtime.wireup_container import WireupContainer

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


def test_the_concrete_satisfies_the_interface() -> None:
    assert isinstance(ScopeFactory(_container()), ScopeFactoryInterface)


async def test_it_opens_a_unit_that_builds_and_releases_a_scoped_service() -> None:
    factory = ScopeFactory(_container())

    async with factory.unit_of_work() as unit:
        session = await unit.get(Session)
        assert not session.closed

    assert session.closed


async def test_each_opened_unit_has_its_own_scoped_service() -> None:
    factory = ScopeFactory(_container())

    async with factory.unit_of_work() as first_unit:
        first = await first_unit.get(Session)
    async with factory.unit_of_work() as second_unit:
        second = await second_unit.get(Session)

    assert first is not second


async def test_a_unit_opened_inside_an_open_one_joins_it() -> None:
    factory = ScopeFactory(_container())

    async with factory.unit_of_work() as outer:
        session = await outer.get(Session)
        async with factory.unit_of_work() as inner:
            assert await inner.get(Session) is session
        # The joined unit ends without releasing what it did not open.
        assert not session.closed

    assert session.closed


async def test_a_unit_asked_not_to_join_is_its_own_and_leaves_the_open_one_current() -> None:
    factory = ScopeFactory(_container())

    async with factory.unit_of_work() as outer:
        session = await outer.get(Session)
        async with factory.unit_of_work(join=False) as inner:
            own = await inner.get(Session)
            assert own is not session
        assert own.closed
        assert not session.closed
        current = current_unit_of_work()
        assert current is not None
        assert await current.get(Session) is session

    assert session.closed
