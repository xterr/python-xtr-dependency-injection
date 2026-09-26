"""A lazy, keyed view of services.

A bus configured to use two of ten registered middleware should build two.
A locator maps names to service keys and builds a service only when it is
asked for by name. It implements :class:`ServiceCollectionInterface` from
:mod:`xtr_service_contracts`: it is sized, async-iterable, and answers
``has`` / ``get`` / ``provided_services``.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING, Generic, TypeVar, cast, final

from typing_extensions import override
from xtr_service_contracts import ServiceCollectionInterface

from xtr_dependency_injection.exception import UnknownLocatorKeyError

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Hashable, Mapping

    from xtr_service_contracts import ContainerInterface

    from xtr_dependency_injection.builder.definition import ServiceKey

__all__ = ["ServiceLocator"]

T = TypeVar("T")


@final
class ServiceLocator(ServiceCollectionInterface[T], Generic[T]):
    """Builds services by name, from a container, only when asked.

    Build one inside a factory that takes ``container: ContainerInterface``::

        def middleware_locator(container: ContainerInterface) -> ServiceLocator[Middleware]:
            return ServiceLocator(container, {name: (Middleware, name) for name in NAMES})
    """

    __slots__ = ("_container", "_entries")

    def __init__(
        self, container: ContainerInterface, entries: Mapping[Hashable, ServiceKey]
    ) -> None:
        """Map each name in ``entries`` to the service key it stands for."""
        self._container = container
        self._entries: dict[Hashable, ServiceKey] = dict(entries)

    def __contains__(self, key: object) -> bool:
        """Return whether ``key`` names a service here."""
        return key in self._entries

    @override
    def has(self, name: Hashable, /) -> bool:
        return name in self._entries

    @override
    async def get(self, name: Hashable, /) -> T:
        """Return the service named ``name``, building it if needed.

        Raises:
            UnknownLocatorKeyError: If ``name`` names nothing here.
        """
        if name not in self._entries:
            raise UnknownLocatorKeyError(name, tuple(self._entries))
        provided, qualifier = self._entries[name]
        return cast("T", await self._container.get(provided, qualifier))

    @override
    def provided_services(self) -> Mapping[Hashable, type[object]]:
        return MappingProxyType({name: key[0] for name, key in self._entries.items()})

    @override
    def __len__(self) -> int:
        return len(self._entries)

    @override
    async def __aiter__(self) -> AsyncIterator[tuple[Hashable, T]]:
        for name in self._entries:
            yield name, await self.get(name)
