"""Read a config field that takes one entry or several."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar, cast

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["one_or_many"]

_T = TypeVar("_T")


def one_or_many(value: _T | Sequence[_T]) -> tuple[_T, ...]:
    """Return ``value`` as a tuple of entries: a list or a tuple is several, anything else one.

    For a bundle config field an application writes either way —
    ``"redis://a"`` or ``["array", "redis://a"]``. Only lists and tuples count
    as several, because a string is a sequence too, and is one entry. Whether
    each entry is valid is the bundle's to check.
    """
    if isinstance(value, (list, tuple)):
        return tuple(cast("Sequence[_T]", value))

    return (cast("_T", value),)
