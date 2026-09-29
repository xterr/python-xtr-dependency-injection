"""A unit of work: one scope shared by everything run for one request, message or command."""

from __future__ import annotations

from collections.abc import (
    AsyncIterator,  # noqa: TC003 — the engine reads the factory's return annotation
)
from typing import TYPE_CHECKING, TypeVar, final

import pytest
import wireup
from typing_extensions import override
from xtr_service_contracts import ContainerInterface

from xtr_dependency_injection import Injected, bind_callable, current_unit_of_work, unit_of_work
from xtr_dependency_injection.exception import InvalidArgumentTypeError
from xtr_dependency_injection.runtime.wireup_container import WireupContainer

if TYPE_CHECKING:
    from collections.abc import Hashable

T = TypeVar("T")

pytestmark = pytest.mark.anyio


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
    engine = wireup.create_async_container(
        injectables=[wireup.injectable(session_factory, lifetime="scoped")],
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
        injectables=[wireup.injectable(session_factory, lifetime="scoped")],
        config={"app": {"name": "shop"}},
    )
    container = WireupContainer(engine)

    async with unit_of_work(container) as unit:
        assert unit.has(Session)
        assert unit.get_parameter("app.name") == "shop"
        assert unit.has_parameter("app")


async def test_a_container_no_kernel_built_is_refused() -> None:
    with pytest.raises(InvalidArgumentTypeError, match="kernel-provided container"):
        async with unit_of_work(_Foreign()):
            pass


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
