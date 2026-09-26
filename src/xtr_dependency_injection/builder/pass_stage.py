"""The five stages a compiler pass runs in.

The kernel runs every pass of one stage before any pass of the next; within
a stage, passes go by priority descending, ties by collection order.
"""

from __future__ import annotations

from enum import Enum

__all__ = ["PassStage"]


class PassStage(Enum):
    """The order the stages execute in."""

    BEFORE_OPTIMIZATION = "before_optimization"
    OPTIMIZE = "optimize"
    BEFORE_REMOVING = "before_removing"
    REMOVE = "remove"
    AFTER_REMOVING = "after_removing"
