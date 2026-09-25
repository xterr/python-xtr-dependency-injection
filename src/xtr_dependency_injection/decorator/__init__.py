"""Markers the kernel reads from scanned objects. Each only records; none has behaviour."""

from __future__ import annotations

from .as_decorator import Inner, InnerMarker, as_decorator
from .compiler_pass import compiler_pass
from .exclude import exclude
from .lifecycle import on_boot, on_shutdown
from .when import when, when_not

__all__ = [
    "Inner",
    "InnerMarker",
    "as_decorator",
    "compiler_pass",
    "exclude",
    "on_boot",
    "on_shutdown",
    "when",
    "when_not",
]
