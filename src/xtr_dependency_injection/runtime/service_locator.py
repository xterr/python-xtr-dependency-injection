"""A lazy, keyed view of services — Symfony's tagged locator.

A bus configured to use two of ten registered middleware should build two.
A locator maps names to service keys and builds a service only when it is
asked for by name.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Generic, TypeVar, cast, final

from xtr_dependency_injection.exception import UnknownLocatorKeyError

if TYPE_CHECKING:
    from collections.abc import Hashable, KeysView, Mapping

    from wireup import AsyncContainer

    from xtr_dependency_injection.builder.definition import ServiceKey

__all__ = ["ServiceLocator"]

T = TypeVar("T")


@final
class ServiceLocator(Generic[T]):
    """Builds services by name, from a container, only when asked.

    Build one inside a factory that takes ``container: AsyncContainer``::

        def middleware_locator(container: AsyncContainer) -> ServiceLocator[MiddlewareInterface]:
            return ServiceLocator(container, {name: (MiddlewareInterface, name) for name in NAMES})
    """

    __slots__ = ("_container", "_entries")

    def __init__(self, container: AsyncContainer, entries: Mapping[Hashable, ServiceKey]) -> None:
        """Map each name in ``entries`` to the service key it stands for."""
        self._container = container
        self._entries = dict(entries)

    def __contains__(self, key: object) -> bool:
        """Return whether ``key`` names a service here."""
        return key in self._entries

    def keys(self) -> KeysView[Hashable]:
        """Return every name this locator holds."""
        return self._entries.keys()

    async def get(self, key: Hashable) -> T:
        """Return the service named ``key``, building it if needed.

        Raises:
            UnknownLocatorKeyError: If ``key`` names nothing here.
        """
        if key not in self._entries:
            raise UnknownLocatorKeyError(key, tuple(self._entries))
        provided, qualifier = self._entries[key]
        return cast("T", await self._container.get(provided, qualifier))
