"""A kernel whose bundles and hooks have booted; shut it down to release everything."""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, cast, final

import wireup

from xtr_dependency_injection.compiler._wireup_bridge import (
    parameter_injections,
    to_engine_signature,
)
from xtr_dependency_injection.runtime.wireup_container import WireupContainer

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from types import TracebackType

    from wireup import AsyncContainer
    from xtr_service_contracts import ContainerInterface

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

    __slots__ = ("_bundles", "_engine", "_on_shutdown", "_shut_down", "container", "kernel")

    container: ContainerInterface
    kernel: KernelInterface

    def __init__(
        self,
        container: AsyncContainer,
        kernel: KernelInterface,
        bundles: Sequence[AnyBundle],
        on_shutdown: Sequence[Callable[..., object]],
    ) -> None:
        """Hold what shutdown needs: the booted bundles and the application's hooks."""
        self._engine = container
        self.container = WireupContainer(container)
        self.kernel = kernel
        self._bundles = tuple(bundles)
        self._on_shutdown = tuple(on_shutdown)
        self._shut_down = False

    async def shutdown(self) -> None:
        """Run the application's ``@on_shutdown`` hooks, then every bundle's, then close.

        Bundles shut down in reverse order; the container is always closed —
        running every generator factory's cleanup — even when a step aborts.
        An ``Exception`` from any step does not stop the others, and they are
        raised together once the container has closed; a ``BaseException`` (a
        cancellation) closes the container, then propagates. A second call
        does nothing.

        Raises:
            ExceptionGroup: If any step raised an ``Exception``.
        """
        if self._shut_down:
            return
        self._shut_down = True
        errors: list[Exception] = []
        try:
            for hook in self._on_shutdown:
                await _attempt(errors, lambda hook=hook: call_injected(self._engine, hook))
            for bundle in reversed(self._bundles):
                await _attempt(errors, lambda bundle=bundle: bundle.shutdown())
        finally:
            await _attempt(errors, self._engine.close)
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
    prepared = _prepare_for_engine(fn, WireupContainer(container))
    result: object = wireup.inject_from_container(container)(prepared)()
    if inspect.isawaitable(result):
        return cast("object", await result)
    return result


def _prepare_for_engine(
    fn: Callable[..., object], resolver: WireupContainer
) -> Callable[..., object]:
    """Return ``fn`` — or a wrapper — with our markers rewritten to wireup's.

    The wrapper is only created when ``fn``'s signature carries our markers;
    unchanged signatures pass through untouched so wireup keeps seeing the
    original callable and its introspection stays honest. A parameter
    injected from a parameter or the environment has its placeholders
    resolved by ``resolver`` first, so the wrapper is then async.
    """
    original = inspect.signature(fn, eval_str=True)
    rewritten = to_engine_signature(original)
    if rewritten is original:
        return fn
    resolved_names = parameter_injections(original)

    async def acall(**kwargs: object) -> object:
        for name in resolved_names:
            if name in kwargs:
                kwargs[name] = await resolver.resolve_env_placeholders(kwargs[name])
        result: object = fn(**kwargs)
        if inspect.isawaitable(result):
            return cast("object", await result)
        return result

    def scall(**kwargs: object) -> object:
        return fn(**kwargs)

    asynchronous = inspect.iscoroutinefunction(fn) or bool(resolved_names)
    wrapper: Callable[..., object] = acall if asynchronous else scall
    setattr(wrapper, "__signature__", rewritten)  # noqa: B010 — wireup reads inspect.signature.
    for attribute in ("__name__", "__qualname__", "__module__"):
        if hasattr(fn, attribute):
            setattr(wrapper, attribute, getattr(fn, attribute))
    return wrapper


async def _attempt(errors: list[Exception], step: Callable[[], object]) -> None:
    try:
        result = step()
        if inspect.isawaitable(result):
            _ = cast("object", await result)
    except Exception as error:  # noqa: BLE001 — collected and raised together.
        errors.append(error)
