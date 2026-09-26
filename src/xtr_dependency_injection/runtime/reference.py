"""Names a service the container provides, for a bundle config to point at."""

from __future__ import annotations

from collections.abc import Hashable
from dataclasses import dataclass
from typing import TYPE_CHECKING, final

from typing_extensions import override

if TYPE_CHECKING:
    from xtr_service_contracts import ContainerInterface

__all__ = ["Reference"]


@final
@dataclass(frozen=True, slots=True)
class Reference:
    """Points a config field at a service registered in the container.

    Use it where a config would otherwise name something the bundle builds
    itself — a DSN, say — to have the bundle use a service the application
    already provides instead: a client with its own connection pool,
    credentials and lifecycle, which the application keeps closing.

    ```python
    LockConfig(resources={"default": Reference(Redis, "locks")})
    ```

    A bundle checks it at boot with :meth:`exists_in`, so a reference to
    nothing fails the application at startup, and fetches it with
    :meth:`resolve` when the service needing it is built.

    Attributes:
        service: The type the service is registered under.
        qualifier: The qualifier it is registered with, if any.
    """

    service: type[object]
    qualifier: Hashable | None = None

    def exists_in(self, container: ContainerInterface) -> bool:
        """Tell whether ``container`` provides the service."""
        return container.has(self.service, self.qualifier)

    async def resolve(self, container: ContainerInterface) -> object:
        """Return the service from ``container``."""
        return await container.get(self.service, self.qualifier)

    @override
    def __str__(self) -> str:
        """Name the service briefly, for a bundle's error message: ``Redis['locks']``."""
        qualifier = "" if self.qualifier is None else f"[{self.qualifier!r}]"
        return f"{self.service.__qualname__}{qualifier}"
