"""A scoped and a singleton service, both tagged for resetting between units of work."""

from __future__ import annotations

from typing import final

from xtr_dependency_injection import as_service, autoconfigure

__all__ = ["Resets", "Resettable", "TokenStorage"]


@autoconfigure(tags=[("kernel.reset", {"method": "reset"})])
class Resettable:
    """Tags every service built from it for resetting."""


@final
@as_service(lifetime="scoped")
class TokenStorage(Resettable):
    """Holds the user of the unit of work it was built for."""

    def __init__(self) -> None:
        self.user: str | None = None

    def reset(self) -> None:
        self.user = None


@final
@as_service
class Resets(Resettable):
    """A singleton counting how often it was reset."""

    def __init__(self) -> None:
        self.count = 0

    def reset(self) -> None:
        self.count += 1
