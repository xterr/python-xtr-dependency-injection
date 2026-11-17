"""A shutdown hook stopping what keeps a unit of work open, as one stopping a worker would."""

from __future__ import annotations

import asyncio
from typing import final

from xtr_dependency_injection import on_shutdown

__all__ = ["PRODUCER", "Producer", "stop_the_producer"]


@final
class Producer:
    """Asked to stop by the hook; journals when it was asked. Replaced by each test."""

    def __init__(self) -> None:
        self.stop = asyncio.Event()
        self.journal: list[str] = []


PRODUCER = Producer()


@on_shutdown
def stop_the_producer() -> None:
    PRODUCER.journal.append("asked to stop")
    PRODUCER.stop.set()
