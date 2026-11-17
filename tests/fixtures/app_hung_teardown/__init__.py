"""A scoped service whose teardown waits for the test to let it finish."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import final

from xtr_dependency_injection import as_service

__all__ = ["GATE", "Gate", "Hung", "hung"]


@final
class Gate:
    """When the teardown started, and when it may finish; replaced by each test."""

    def __init__(self) -> None:
        self.closing = asyncio.Event()
        self.release = asyncio.Event()
        self.closed = False


GATE = Gate()


@final
class Hung:
    """The scoped service built."""


@as_service(lifetime="scoped")
async def hung() -> AsyncIterator[Hung]:
    """Yield one; on teardown, wait until the test releases it."""
    yield Hung()
    GATE.closing.set()
    _ = await GATE.release.wait()
    GATE.closed = True
