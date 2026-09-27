"""Fixture app: a transient resettable service a factory builds without weak references."""

from __future__ import annotations

from typing import ClassVar, final

from xtr_dependency_injection import as_service, autoconfigure


@autoconfigure(tags=[("kernel.reset", {"method": "clear"})])
class Resettable:
    """Tags every service built from it for resetting."""

    __slots__: ClassVar[tuple[str, ...]] = ()


@final
class SlottedSession(Resettable):
    """Refuses weak references: its slots leave ``__weakref__`` out."""

    __slots__: ClassVar[tuple[str, ...]] = ("entries",)

    def __init__(self) -> None:
        self.entries: list[str] = []

    def clear(self) -> None:
        self.entries.clear()


@as_service(lifetime="transient")
def session() -> SlottedSession:
    return SlottedSession()
