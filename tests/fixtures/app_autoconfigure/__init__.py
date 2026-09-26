"""Fixtures for the todo-16 autoconfiguration tests."""

from __future__ import annotations

from typing_extensions import override
from xtr_service_contracts import ResetInterface

from xtr_dependency_injection.decorator.as_service import as_service


@as_service()
class Buffer(ResetInterface):
    """A nominal ``ResetInterface`` — the ``kernel.reset`` autoconfigure catches it."""

    def __init__(self) -> None:
        self.items: list[str] = []
        self.resets: int = 0

    @override
    def reset(self) -> None:
        self.items.clear()
        self.resets += 1


@as_service()
class StructuralOnly:
    """Has ``reset()`` but does NOT inherit ``ResetInterface`` — must NOT be tagged."""

    def __init__(self) -> None:
        self.resets: int = 0

    def reset(self) -> None:
        self.resets += 1
