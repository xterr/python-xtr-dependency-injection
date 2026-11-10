"""The five stages a compiler pass runs in.

The :class:`~xtr_dependency_injection.compiler.pass_config.PassConfig` runs
every pass of one stage before any pass of the next; within a stage, passes go
by priority descending, ties by registration order.
"""

from __future__ import annotations

from enum import Enum
from typing import Final

__all__ = ["BUNDLE_PASS_PRIORITY", "PassStage"]

BUNDLE_PASS_PRIORITY: Final = -10000
"""Where a bundle overriding ``process`` runs: last in ``BEFORE_OPTIMIZATION``.

The later stages still run after it.
"""


class PassStage(Enum):
    """The order the stages execute in."""

    BEFORE_OPTIMIZATION = "before_optimization"
    OPTIMIZE = "optimize"
    BEFORE_REMOVING = "before_removing"
    REMOVE = "remove"
    AFTER_REMOVING = "after_removing"
