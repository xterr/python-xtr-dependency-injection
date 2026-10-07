"""The container-backed :class:`ScopeFactoryInterface` the kernel registers."""

from __future__ import annotations

from typing import TYPE_CHECKING, final

from typing_extensions import override

from .scope_factory_interface import ScopeFactoryInterface
from .unit_of_work import unit_of_work

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager

    from xtr_service_contracts import ContainerInterface

__all__ = ["ScopeFactory"]


@final
class ScopeFactory(ScopeFactoryInterface):
    """Opens units of work on one container, delegating to :func:`unit_of_work`."""

    __slots__ = ("_container",)

    def __init__(self, container: ContainerInterface) -> None:
        """Hold the container whose services every unit this factory opens resolves."""
        self._container = container

    @override
    def unit_of_work(self, *, join: bool = True) -> AbstractAsyncContextManager[ContainerInterface]:
        """Open a unit of work on the held container — or join the one it has open.

        Raises:
            InvalidArgumentTypeError: On entering, if the held container is
                not one a kernel built. The kernel registers this factory
                with its own container, so only a hand-built one can be.
        """
        return unit_of_work(self._container, join=join)
