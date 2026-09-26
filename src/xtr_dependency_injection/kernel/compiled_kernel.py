"""A built container, before boot — usable as is, as a FastAPI setup needs."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, final

from xtr_dependency_injection.exception import KernelAlreadyBootedError
from xtr_dependency_injection.runtime.wireup_container import WireupContainer

from .booted_kernel import BootedKernel, call_injected

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable, Sequence
    from contextlib import AbstractAsyncContextManager

    from wireup import AsyncContainer
    from xtr_service_contracts import ContainerInterface

    from xtr_dependency_injection.bundle.bundle import AnyBundle
    from xtr_dependency_injection.diagnostics import KernelReport

    from .kernel_interface import KernelInterface

__all__ = ["CompiledKernel"]


@final
class CompiledKernel:
    """A compiled kernel: its container and report, ready to boot once.

    The container exists already, so a framework integration can be wired
    before the application starts; ``lifespan`` then boots and shuts down
    around the application's life. Framework integrations that need the
    engine container use ``engine_container(compiled)`` from
    ``xtr_dependency_injection.integration.wireup`` (todo 23).
    """

    __slots__ = (
        "_booted",
        "_bundles",
        "_engine",
        "_info",
        "_on_boot",
        "_on_shutdown",
        "container",
        "report",
    )

    container: ContainerInterface
    report: KernelReport

    def __init__(  # noqa: PLR0913 — everything boot and shutdown need.
        self,
        container: AsyncContainer,
        report: KernelReport,
        *,
        info: KernelInterface,
        bundles: Sequence[AnyBundle],
        on_boot: Sequence[Callable[..., object]],
        on_shutdown: Sequence[Callable[..., object]],
    ) -> None:
        """Hold the container and everything boot and shutdown run."""
        self._engine = container
        self.container = WireupContainer(container)
        self.report = report
        self._info = info
        self._bundles = tuple(bundles)
        self._on_boot = tuple(on_boot)
        self._on_shutdown = tuple(on_shutdown)
        self._booted = False

    async def boot(self) -> BootedKernel:
        """Boot every bundle in order, then run the application's ``@on_boot`` hooks.

        If a step raises, what already booted is shut down in reverse, the
        container is closed, and the error propagates.

        Raises:
            KernelAlreadyBootedError: If this compiled kernel booted before.
        """
        if self._booted:
            raise KernelAlreadyBootedError
        self._booted = True
        booted: list[AnyBundle] = []
        try:
            for bundle in self._bundles:
                # Symfony's setContainer: bundles see the container before their boot runs.
                bundle.container = self.container
                await bundle.boot()
                booted.append(bundle)
            for hook in self._on_boot:
                _ = await call_injected(self._engine, hook)
        except BaseException as error:
            partial = BootedKernel(self._engine, self._info, booted, ())
            try:
                await partial.shutdown()
            except ExceptionGroup as cleanup:
                error.add_note(f"shutting down after the failed boot also failed: {cleanup!r}")
            raise
        return BootedKernel(self._engine, self._info, self._bundles, self._on_shutdown)

    def lifespan(self, app: object, /) -> AbstractAsyncContextManager[None]:
        """Return an ASGI-style lifespan: boot on enter, shut down on exit."""
        del app
        return self._lifespan()

    @asynccontextmanager
    async def _lifespan(self) -> AsyncGenerator[None, None]:
        booted = await self.boot()
        try:
            yield
        finally:
            await booted.shutdown()
