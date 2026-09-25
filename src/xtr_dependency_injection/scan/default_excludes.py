"""Modules the scan leaves out unless told otherwise."""

from __future__ import annotations

from typing import Final

__all__ = ["DEFAULT_EXCLUDES"]

DEFAULT_EXCLUDES: Final[tuple[str, ...]] = (
    "*.tests",
    "*.tests.*",
    "*.test_*",
    "*.conftest",
    "*.__main__",
)
"""``fnmatch`` patterns of module names never imported by a scan.

Tests and entry points are not services, and importing ``__main__`` would
run the application. ``Kernel(exclude=...)`` replaces these; extend them with
``(*DEFAULT_EXCLUDES, "app.scripts.*")``.
"""
