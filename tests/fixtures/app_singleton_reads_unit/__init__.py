"""A singleton whose constructor reads the unit of work open while it is built."""

from __future__ import annotations

from typing import final

from xtr_dependency_injection import as_service, current_unit_of_work

__all__ = ["KeepsUnit"]


@final
@as_service
class KeepsUnit:
    """Would keep whichever unit built it."""

    def __init__(self) -> None:
        self.unit = current_unit_of_work()
