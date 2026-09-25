from __future__ import annotations

from xtr_dependency_injection.decorator.lifecycle import (
    LifecycleMarker,
    on_boot,
    on_boot_of,
    on_shutdown,
    on_shutdown_of,
)


def test_a_bare_on_boot_has_priority_zero() -> None:
    @on_boot
    async def warm() -> None: ...

    assert on_boot_of(warm) == LifecycleMarker(0)
    assert on_shutdown_of(warm) is None


def test_on_boot_records_its_priority() -> None:
    @on_boot(priority=3)
    def warm() -> None: ...

    assert on_boot_of(warm) == LifecycleMarker(3)


def test_on_shutdown_records_its_priority() -> None:
    @on_shutdown(priority=-1)
    def flush() -> None: ...

    assert on_shutdown_of(flush) == LifecycleMarker(-1)
    assert on_boot_of(flush) is None
