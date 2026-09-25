"""How errors and reports name types, service keys and origins — one spelling everywhere."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Hashable

__all__ = ["key_name", "type_name"]


def type_name(obj: object) -> str:
    """Return ``module.QualName`` for a class or function, ``repr`` for anything else.

    A generic alias such as ``Sequence[Plugin]`` has no qualname of its own and
    reads best as written.
    """
    qualname = getattr(obj, "__qualname__", None)
    module = getattr(obj, "__module__", None)
    if isinstance(qualname, str) and isinstance(module, str) and isinstance(obj, type):
        return qualname if module == "builtins" else f"{module}.{qualname}"
    if isinstance(qualname, str) and isinstance(module, str) and callable(obj):
        return f"{module}:{qualname}"
    return repr(obj)


def key_name(key: tuple[object, Hashable | None]) -> str:
    """Return a service key as ``Type`` or ``Type[qualifier]``."""
    provided, qualifier = key
    name = type_name(provided)
    return name if qualifier is None else f"{name}[{qualifier!r}]"
