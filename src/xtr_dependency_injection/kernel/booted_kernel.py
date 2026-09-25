"""A kernel whose bundles and hooks have booted; shut it down to release everything."""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, cast, final

import wireup

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from types import TracebackType

    from wireup import AsyncContainer

    from xtr_dependency_injection.bundle.bundle import AnyBundle

    from .kernel_interface import KernelInterface

__all__ = ["BootedKernel"]


@final
class BootedKernel:
    """A booted kernel: its container, and the shutdown that releases it.

    Use it as an async context manager, which shuts it down on exit::

        async with await kernel.boot() as booted:
            bus = await booted.container.get(MessageBusInterface)
    """

    __slots__ = ("_bundles", "_on_shutdown", "_shut_down", "container", "kernel")

    container: AsyncContainer
    kernel: KernelInterface

    def __init__(
        self,
        container: AsyncContainer,
        kernel: KernelInterface,
        bundles: Sequence[AnyBundle],
        on_shutdown: Sequence[Callable[..., object]],
    ) -> None:
        """Hold what shutdown needs: the booted bundles and the application's hooks."""
        self.container = container
        self.kernel = kernel
        self._bundles = tuple(bundles)
        self._on_shutdown = tuple(on_shutdown)
        self._shut_down = False

    async def shutdown(self) -> None:
        """Run the application's ``@on_shutdown`` hooks, then every bundle's, then close.

        Bundles shut down in reverse order; closing the container runs every
        generator factory's cleanup. Every step runs even if one before it
        raised; all errors are raised together. A second call does nothing.

        Raises:
            ExceptionGroup: If any step raised.
        """
        if self._shut_down:
            return
        self._shut_down = True
        errors: list[Exception] = []
        for hook in self._on_shutdown:
            await _attempt(errors, lambda hook=hook: call_injected(self.container, hook))
        for bundle in reversed(self._bundles):
            await _attempt(errors, lambda bundle=bundle: bundle.shutdown(self.container))
        await _attempt(errors, self.container.close)
        if errors:
            msg = "the kernel failed to shut down cleanly"
            raise ExceptionGroup(msg, errors)

    async def __aenter__(self) -> BootedKernel:
        """Return this kernel."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Shut the kernel down."""
        await self.shutdown()


async def call_injected(container: AsyncContainer, fn: Callable[..., object]) -> object:
    """Call ``fn`` with its ``Injected[...]`` parameters filled from ``container``.

    Sync or async; an awaitable result is awaited.
    """
    result: object = wireup.inject_from_container(container)(fn)()
    if inspect.isawaitable(result):
        return cast("object", await result)
    return result


async def _attempt(errors: list[Exception], step: Callable[[], object]) -> None:
    try:
        result = step()
        if inspect.isawaitable(result):
            _ = cast("object", await result)
    except Exception as error:  # noqa: BLE001 — collected and raised together.
        errors.append(error)
