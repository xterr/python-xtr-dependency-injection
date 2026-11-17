"""A scoped service whose factory waits for the test to let it finish, counting its builds."""

from __future__ import annotations

import asyncio
from typing import final

from xtr_dependency_injection import as_service

__all__ = ["GATE", "Slow", "slow"]


@final
class Gate:
    """When the factory started, and when it may finish; reset by each test."""

    def __init__(self) -> None:
        self.building = asyncio.Event()
        self.release = asyncio.Event()
        self.built = 0


GATE = Gate()


@final
class Slow:
    """The scoped service built."""


@as_service(lifetime="scoped")
async def slow() -> Slow:
    """Build one, once the test releases it."""
    GATE.built += 1
    GATE.building.set()
    _ = await GATE.release.wait()
    return Slow()
