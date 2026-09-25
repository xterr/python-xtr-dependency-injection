from __future__ import annotations

import pytest

from xtr_dependency_injection.runtime.services_resetter import ServicesResetter

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
