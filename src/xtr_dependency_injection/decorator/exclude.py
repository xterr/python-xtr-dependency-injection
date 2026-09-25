"""Keeping an object out of the scan in every environment."""

from __future__ import annotations

from typing import Final, TypeVar

from ._marker import own_marker, set_marker

__all__ = ["exclude", "is_excluded"]

T = TypeVar("T")

_EXCLUDE: Final = "__xtr_exclude__"


def exclude(obj: T, /) -> T:
    """Leave the decorated object out of every scan: never a service, never autoconfigured."""
    return set_marker(obj, _EXCLUDE, True)  # noqa: FBT003 — a marker's value, not a flag argument.


def is_excluded(obj: object) -> bool:
    """Return whether ``@exclude`` was put on ``obj`` itself."""
    return own_marker(obj, _EXCLUDE) is True
