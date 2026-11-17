from __future__ import annotations

import asyncio
import gc
import weakref

import pytest

from tests.fixtures.app_resettable_units import Resets, TokenStorage
from xtr_dependency_injection import unit_of_work
from xtr_dependency_injection.integration.wireup import create_container
from xtr_dependency_injection.runtime.services_resetter import ServicesResetter
from xtr_dependency_injection.runtime.wireup_container import WireupContainer

pytestmark = pytest.mark.anyio


class Buffer:
    def __init__(self, log: list[str], name: str) -> None:
        self.log: list[str] = log
        self.name: str = name

    def reset(self) -> None:
        self.log.append(f"sync {self.name}")

    async def clear(self) -> None:
        self.log.append(f"async {self.name}")


async def test_tracked_services_are_reset_in_tracking_order() -> None:
    log: list[str] = []
    first, second = Buffer(log, "first"), Buffer(log, "second")
    resetter = ServicesResetter()
    resetter.track(first, "reset")
    resetter.track(second, "clear")

    await resetter.reset()

    assert log == ["sync first", "async second"]


async def test_an_instance_is_tracked_once() -> None:
    log: list[str] = []
    buffer = Buffer(log, "only")
    resetter = ServicesResetter()
    resetter.track(buffer, "reset")
    resetter.track(buffer, "reset")

    await resetter.reset()

    assert log == ["sync only"]


async def test_nothing_tracked_resets_nothing() -> None:
    await ServicesResetter().reset()


async def test_a_collected_instance_is_forgotten() -> None:
    log: list[str] = []
    resetter = ServicesResetter()
    resetter.track(Buffer(log, "gone"), "reset")

    await resetter.reset()

    assert log == []


class Slotted:
    __slots__: tuple[str, ...] = ()
    calls: int = 0

    def reset(self) -> None:
        type(self).calls += 1


async def test_an_instance_without_weak_references_is_kept_alive() -> None:
    Slotted.calls = 0
    resetter = ServicesResetter()
    resetter.track(Slotted(), "reset")

    await resetter.reset()
    await resetter.reset()

    assert Slotted.calls == 2


async def test_a_strongly_held_instance_is_tracked_once() -> None:
    Slotted.calls = 0
    instance = Slotted()
    resetter = ServicesResetter()
    resetter.track(instance, "reset")
    resetter.track(instance, "reset")

    await resetter.reset()

    assert Slotted.calls == 1


async def test_collected_instances_are_forgotten_without_a_reset() -> None:
    resetter = ServicesResetter()
    for _ in range(1000):
        resetter.track(Buffer([], "gone"), "reset")
    _ = gc.collect()

    assert len(resetter._tracked) == 0


async def test_reset_follows_tracking_order_after_collections() -> None:
    log: list[str] = []
    first, third = Buffer(log, "first"), Buffer(log, "third")
    resetter = ServicesResetter()
    resetter.track(first, "reset")
    resetter.track(Buffer(log, "second"), "reset")
    resetter.track(third, "reset")
    _ = gc.collect()

    await resetter.reset()

    assert log == ["sync first", "sync third"]


async def test_reset_skips_a_reference_whose_referent_is_gone() -> None:
    log: list[str] = []
    alive = Buffer(log, "alive")
    resetter = ServicesResetter()
    resetter.track(alive, "reset")
    orphan = Buffer([], "orphan")
    resetter._tracked[id(orphan)] = (weakref.ref(orphan), "reset")
    del orphan
    _ = gc.collect()

    await resetter.reset()

    assert log == ["sync alive"]


async def test_every_service_is_reset_when_one_fails_and_the_failures_are_raised_together() -> None:
    reset: list[str] = []

    class Failing:
        def reset(self) -> None:
            reset.append("failing")
            msg = "cannot reset"
            raise RuntimeError(msg)

    class Fine:
        def reset(self) -> None:
            reset.append("fine")

    failing, fine = Failing(), Fine()
    resetter = ServicesResetter()
    resetter.track(failing, "reset")
    resetter.track(fine, "reset")

    with pytest.raises(ExceptionGroup) as caught:
        await resetter.reset()

    assert reset == ["failing", "fine"]
    assert [type(error) for error in caught.value.exceptions] == [RuntimeError]


def _units_container() -> WireupContainer:
    return WireupContainer(create_container([], scan=["tests.fixtures.app_resettable_units"]))


async def test_a_reset_from_one_unit_leaves_another_units_scoped_state_alone() -> None:
    container = _units_container()
    resetter = await container.get(ServicesResetter)
    ready = {"alice": asyncio.Event(), "bob": asyncio.Event()}
    go = {"alice": asyncio.Event(), "bob": asyncio.Event()}

    async def message(name: str) -> tuple[str, str | None]:
        async with unit_of_work(container, join=False) as unit:
            storage = await unit.get(TokenStorage)
            storage.user = name
            ready[name].set()
            _ = await go[name].wait()
            seen = storage.user
            await resetter.reset()
        return name, seen

    alice = asyncio.create_task(message("alice"))
    bob = asyncio.create_task(message("bob"))
    _ = await ready["alice"].wait()
    _ = await ready["bob"].wait()
    go["alice"].set()
    first = await alice
    go["bob"].set()
    second = await bob

    assert [first, second] == [("alice", "alice"), ("bob", "bob")]


async def test_a_scoped_resettable_is_not_tracked() -> None:
    container = _units_container()
    resetter = await container.get(ServicesResetter)

    async with unit_of_work(container) as unit:
        storage = await unit.get(TokenStorage)
        storage.user = "alice"
        await resetter.reset()

        assert storage.user == "alice"


async def test_a_singleton_resettable_is_still_reset() -> None:
    container = _units_container()
    resetter = await container.get(ServicesResetter)
    resets = await container.get(Resets)

    await resetter.reset()

    assert resets.count == 1
