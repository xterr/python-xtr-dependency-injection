"""Boot and shutdown must close the container even when aborted by a ``BaseException``.

A ``BaseException`` — a cancellation, a ``KeyboardInterrupt`` — must not leave the
container open: a boot that is aborted rolls back what it started and closes the
container, and a shutdown that is aborted still closes it. These tests raise a
plain ``Abort(BaseException)`` so they never touch the interpreter's own
``KeyboardInterrupt`` / ``CancelledError`` handling.
"""

from __future__ import annotations

# wireup evaluates a factory's return annotation while the container builds, so
# ``Iterator`` cannot be deferred into a ``TYPE_CHECKING`` block.
from collections.abc import Iterator  # noqa: TC003
from typing import TYPE_CHECKING

import pytest
from typing_extensions import override

from xtr_dependency_injection.bundle import Bundle, as_bundle, required_bundle
from xtr_dependency_injection.kernel import Kernel

if TYPE_CHECKING:
    from xtr_dependency_injection.builder.container_builder import ContainerBuilder
    from xtr_dependency_injection.builder.service_configurator import ServiceConfigurator

pytestmark = pytest.mark.anyio

# A real, importable package for the kernel to name; nothing is scanned from it
# because every test passes ``resources=()`` and supplies its bundles by hand.
_PACKAGE = "tests.fixtures.app_kernel"

_events: list[str] = []
_closed: list[bool] = []


class Abort(BaseException):
    """A non-``Exception`` abort, like ``KeyboardInterrupt``, safe to raise in a test."""


class Res:
    """A service built by a generator factory whose cleanup records that it closed."""


def res() -> Iterator[Res]:
    """Yield a ``Res``; after the container closes, record that its cleanup ran."""
    yield Res()
    _closed.append(True)


@pytest.fixture(autouse=True)
def _reset() -> None:
    _events.clear()
    _closed.clear()


@as_bundle("res_boot")
class BootResolvingBundle(Bundle):
    """Registers the generator factory and resolves it during boot, so it is open."""

    @override
    def load_extension(
        self, config: object, services: ServiceConfigurator, builder: ContainerBuilder
    ) -> None:
        del config, builder
        _ = services.set(res)

    @override
    async def boot(self) -> None:
        assert self.container is not None
        _ = await self.container.get(Res)
        _events.append("boot:res_boot")

    @override
    async def shutdown(self) -> None:
        _events.append("shutdown:res_boot")


@required_bundle(BootResolvingBundle)
@as_bundle("res_abort_boot")
class AbortingBootBundle(Bundle):
    """Boots after ``res_boot`` and aborts with a ``BaseException``."""

    @override
    async def boot(self) -> None:
        raise Abort("boot aborted")


@as_bundle("res_abort_shutdown")
class AbortingShutdownBundle(Bundle):
    """Resolves the generator factory at boot, then aborts during shutdown."""

    @override
    def load_extension(
        self, config: object, services: ServiceConfigurator, builder: ContainerBuilder
    ) -> None:
        del config, builder
        _ = services.set(res)

    @override
    async def boot(self) -> None:
        assert self.container is not None
        _ = await self.container.get(Res)

    @override
    async def shutdown(self) -> None:
        raise Abort("shutdown aborted")


async def test_a_boot_aborted_by_a_base_exception_closes_the_container() -> None:
    compiled = Kernel(
        _PACKAGE,
        env="dev",
        bundles={BootResolvingBundle: {"all": True}, AbortingBootBundle: {"all": True}},
        resources=(),
    ).build()

    with pytest.raises(Abort):
        _ = await compiled.boot()

    assert _events == ["boot:res_boot", "shutdown:res_boot"]
    assert _closed == [True]


async def test_a_shutdown_aborted_by_a_base_exception_still_closes_the_container() -> None:
    booted = await Kernel(
        _PACKAGE,
        env="dev",
        bundles={AbortingShutdownBundle: {"all": True}},
        resources=(),
    ).boot()

    with pytest.raises(Abort):
        await booted.shutdown()

    assert _closed == [True]
