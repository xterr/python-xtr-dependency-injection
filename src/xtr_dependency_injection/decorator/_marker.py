"""Reading and writing the attributes decorators leave on functions and classes.

A marker is read from the object's *own* namespace only. A subclass inherits
its parent's attributes, but a ``@when("dev")`` or ``@on_boot`` on a parent
says nothing about the subclass — the scanner meets both, and must not act on
the parent's decision twice.
"""

from __future__ import annotations

from typing import TypeVar, cast

__all__ = ["own_marker", "set_marker"]

T = TypeVar("T")


def own_marker(obj: object, name: str) -> object | None:
    """Return the marker ``name`` set on ``obj`` itself, or ``None``."""
    namespace = cast("dict[str, object]", getattr(obj, "__dict__", {}))
    return namespace.get(name)


def set_marker(obj: T, name: str, value: object) -> T:
    """Set the marker ``name`` on ``obj`` and return ``obj`` unchanged otherwise."""
    setattr(obj, name, value)
    return obj
