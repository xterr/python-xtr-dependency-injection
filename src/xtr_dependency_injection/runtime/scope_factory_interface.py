"""The typed seam a service injects to open a unit of work, never the container.

A service that must open a scope — a message bus running every message in one,
a worker starting a fresh one per received message — would otherwise take the
whole :class:`~xtr_service_contracts.ContainerInterface` only to call
:func:`~xtr_dependency_injection.unit_of_work` on it. Injecting a
:class:`ScopeFactoryInterface` instead hands it exactly that one power and
nothing else.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager

    from xtr_service_contracts import ContainerInterface

__all__ = ["ScopeFactoryInterface"]


@runtime_checkable
class ScopeFactoryInterface(Protocol):
    """Opens a unit of work on the container it was built for.

    The one method mirrors
    :func:`~xtr_dependency_injection.unit_of_work`: it opens a scope — or
    joins the one the container has open — and yields the scoped container,
    which resolves scoped services as well as singletons.
    """

    def unit_of_work(self, *, join: bool = True) -> AbstractAsyncContextManager[ContainerInterface]:
        """Open a unit of work — or join the one already open — and yield its container.

        Args:
            join: Join the unit the container has open, if any. ``False``
                opens one of its own inside it, for work that is new rather
                than part of what is under way.

        Raises:
            InvalidArgumentTypeError: On entering, if the factory was built
                for a container no kernel built.
        """
        ...
