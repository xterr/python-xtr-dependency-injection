"""The kernel's :class:`ContainerInterface` implementation over a wireup ``AsyncContainer``.

Bundles receive one of these as ``self.container`` before their ``boot`` runs.
It is the only place a wireup container is wrapped for the public
``ContainerInterface`` seam; the engine stays out of every consumer's sight.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar, cast, final

from typing_extensions import override
from wireup.errors import UnknownParameterError
from xtr_service_contracts import ContainerInterface

from xtr_dependency_injection.compiler._wireup_bridge import is_registered
from xtr_dependency_injection.exception import (
    ParameterNotFoundError,
    ServiceNotFoundError,
    ServiceResolutionError,
)

if TYPE_CHECKING:
    from collections.abc import Hashable

    from wireup import AsyncContainer

__all__ = ["WireupContainer"]

T = TypeVar("T")

_SCOPE_ADVICE = (
    "scoped and transient services are built inside a scope; resolve them from an "
    "injected callable, or from bind_callable(container, target, per_call_scope=True)"
)
"""How this package resolves a scoped or transient service, for the get() advice."""


@final
class WireupContainer(ContainerInterface):
    """Wraps a wireup ``AsyncContainer`` behind :class:`ContainerInterface`."""

    __slots__ = ("_container",)

    def __init__(self, container: AsyncContainer) -> None:
        """Wrap ``container`` — no state of our own."""
        self._container = container

    @override
    async def get(self, service: type[T], /, qualifier: Hashable | None = None) -> T:
        if not is_registered(self._container, service, qualifier):
            raise ServiceNotFoundError((service, qualifier))
        try:
            return await self._container.get(service, qualifier)
        except ServiceNotFoundError:
            raise
        except Exception as error:
            reason = str(error)
            advice = _SCOPE_ADVICE if "scope mismatch" in reason.lower() else None
            raise ServiceResolutionError((service, qualifier), reason, advice=advice) from error

    @override
    def has(self, service: type[object], /, qualifier: Hashable | None = None) -> bool:
        return is_registered(self._container, service, qualifier)

    @override
    def get_parameter(self, name: str, /) -> object:
        try:
            return cast("object", self._container.config.get(name))
        except UnknownParameterError as error:
            raise ParameterNotFoundError(name) from error

    @override
    def has_parameter(self, name: str, /) -> bool:
        try:
            _ = cast("object", self._container.config.get(name))
        except UnknownParameterError:
            return False
        return True

    def _engine(self) -> AsyncContainer:  # pyright: ignore[reportUnusedFunction] — called cross-module via SLF001.
        """Return the wrapped engine container — for kernel-internal use only.

        Public consumers see this container behind :class:`ContainerInterface`;
        the kernel's internal glue (``bind_callable``, ``call_injected``,
        ``testing.boot_for_test``) needs the raw engine to enter scopes, run
        overrides and inject callables.
        """
        return self._container
