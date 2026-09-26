"""Give a factory built per qualifier a name of its own."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, TypeVar, cast

if TYPE_CHECKING:
    import types

__all__ = ["named_factory"]

_F = TypeVar("_F", bound=Callable[..., object])


def named_factory(factory: _F, name: str) -> _F:
    """Name ``factory`` ``name`` and return it.

    A bundle registering one factory per configured name — a store per lock
    resource, a pool per cache pool — builds each as a closure of the same
    function, so every one would be reported under that function's name. The
    container's report, and every error naming the factory, reads far better
    with ``lock_store_reports`` than with ``store``. Only the names change:
    the function, and how the engine calls it, stay as they are.

    The function itself is renamed, not a copy of it: give it a function made
    for this name — a closure built per qualifier — never one shared by others.
    """
    # A factory registered with the container is a function; only functions carry these names.
    function = cast("types.FunctionType", factory)
    function.__name__ = name
    function.__qualname__ = name
    return factory
