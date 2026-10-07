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


@required_bundle(BootResolvingBundle)
@as_bundle("res_abort_shutdown_first")
class AbortingFirstShutdownBundle(Bundle):
    """Shuts down before ``res_boot``, which it requires, and aborts with a ``BaseException``."""

    @override
    async def shutdown(self) -> None:
        raise Abort("shutdown aborted")


async def test_a_shutdown_aborted_by_a_base_exception_still_runs_every_other_step() -> None:
    booted = await Kernel(
        _PACKAGE,
        env="dev",
        bundles={AbortingFirstShutdownBundle: {"all": True}},
        resources=(),
    ).boot()

    with pytest.raises(Abort):
        await booted.shutdown()

    assert _events == ["boot:res_boot", "shutdown:res_boot"]
    assert _closed == [True]


@as_bundle("res_fails_shutdown")
class FailingShutdownBundle(Bundle):
    """Boots fine, then fails as it shuts down."""

    @override
    async def shutdown(self) -> None:
        message = "shutdown failed"
        raise RuntimeError(message)


@required_bundle(FailingShutdownBundle)
@as_bundle("res_fails_boot")
class FailingBootBundle(Bundle):
    """Boots after ``res_fails_shutdown`` and fails."""

    @override
    async def boot(self) -> None:
        message = "boot failed"
        raise ValueError(message)


async def test_a_boot_failure_keeps_its_error_and_notes_the_failed_rollback() -> None:
    compiled = Kernel(
        _PACKAGE,
        env="dev",
        bundles={FailingBootBundle: {"all": True}},
        resources=(),
    ).build()

    with pytest.raises(ValueError, match="boot failed") as caught:
        _ = await compiled.boot()

    (note,) = caught.value.__notes__
    assert note.startswith("shutting down after the failed boot also failed")
    assert "shutdown failed" in note


async def test_the_container_of_the_bundle_whose_boot_failed_is_cleared() -> None:
    # The failed bundle never joins the booted ones, so the rollback's own
    # clean-up skips it: boot has to take back what it handed over.
    compiled = Kernel(
        _PACKAGE,
        env="dev",
        bundles={FailingBootBundle: {"all": True}},
        resources=(),
    ).build()
    bundle = next(b for b in compiled._bundles if isinstance(b, FailingBootBundle))

    with pytest.raises(ValueError, match="boot failed"):
        _ = await compiled.boot()

    assert bundle.container is None


@as_bundle("res_aborts_rollback")
class AbortingRollbackBundle(Bundle):
    """Boots fine, then aborts the rollback with a ``BaseException``."""

    @override
    async def shutdown(self) -> None:
        raise Abort("rollback aborted")


@required_bundle(AbortingRollbackBundle)
@as_bundle("res_fails_boot_after_abort")
class FailingBootAfterAbortBundle(Bundle):
    """Boots after ``res_aborts_rollback`` and fails."""

    @override
    async def boot(self) -> None:
        message = "boot failed"
        raise ValueError(message)


async def test_a_boot_failure_keeps_its_error_when_the_rollback_is_aborted() -> None:
    compiled = Kernel(
        _PACKAGE,
        env="dev",
        bundles={FailingBootAfterAbortBundle: {"all": True}},
        resources=(),
    ).build()

    with pytest.raises(ValueError, match="boot failed") as caught:
        _ = await compiled.boot()

    (note,) = caught.value.__notes__
    assert "rollback aborted" in note


@as_bundle("res_container_cleared")
class ContainerClearedBundle(Bundle):
    """Records its container during shutdown so the clean-up afterwards is observable."""

    seen_during_shutdown: object = None

    @override
    async def shutdown(self) -> None:
        ContainerClearedBundle.seen_during_shutdown = self.container


async def test_a_bundles_container_is_set_during_shutdown_and_cleared_after() -> None:
    ContainerClearedBundle.seen_during_shutdown = None
    booted = await Kernel(
        _PACKAGE,
        env="dev",
        bundles={ContainerClearedBundle: {"all": True}},
        resources=(),
    ).boot()
    bundle = next(b for b in booted._bundles if isinstance(b, ContainerClearedBundle))
    assert bundle.container is not None

    await booted.shutdown()

    assert ContainerClearedBundle.seen_during_shutdown is not None
    assert bundle.container is None
