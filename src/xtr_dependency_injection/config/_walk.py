"""Walking a configuration value — and rebuilding only what changed.

Configs are frozen dataclasses, msgspec ``Struct``s or pydantic models,
nested in mappings, sequences and sets. Resolving parameter references and
environment placeholders both need the same walk: visit every leaf (a
string, a number, anything without fields), and rebuild each container whose
leaves changed — a dataclass through ``dataclasses.replace`` (so its
validation runs again), a ``Struct`` through ``msgspec.structs.replace``, a
model through ``model_copy`` — leaving the rest as the very same objects.
"""

from __future__ import annotations

import dataclasses
import importlib
from collections.abc import Mapping
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

__all__ = ["leaves", "rebuild"]


def leaves(value: object) -> Iterator[object]:
    """Yield every leaf of ``value``, mapping keys included; each container is visited once."""
    yield from _leaves(value, set())


def _leaves(value: object, seen: set[int]) -> Iterator[object]:
    children = _children(value)
    if children is None:
        yield value
        return
    if id(value) in seen:
        return
    seen.add(id(value))
    for child in children:
        yield from _leaves(child, seen)


def _children(value: object) -> tuple[object, ...] | None:
    """Return what ``value`` contains, or ``None`` when it is a leaf."""
    if isinstance(value, (str, bytes, int, float, type(None))):
        return None
    if isinstance(value, Mapping):
        mapping = cast("Mapping[object, object]", value)
        return (*mapping.keys(), *mapping.values())
    if isinstance(value, (list, tuple, set, frozenset)):
        return tuple(cast("list[object]", value))
    names = _field_names(value)
    if not names:
        return None
    return tuple(cast("object", getattr(value, name)) for name in names)


def _field_names(value: object) -> tuple[str, ...]:
    """Return the constructor fields of a dataclass, msgspec ``Struct`` or pydantic model."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return tuple(field.name for field in dataclasses.fields(value) if field.init)
    struct_fields = cast("tuple[str, ...] | None", getattr(type(value), "__struct_fields__", None))
    if struct_fields is not None:
        return struct_fields
    model_fields = cast("Mapping[str, object] | None", getattr(type(value), "model_fields", None))
    if model_fields is not None and hasattr(value, "model_copy"):
        return tuple(model_fields)
    return ()


def rebuild(value: object, leaf: Callable[[object], object]) -> object:
    """Return ``value`` with every leaf replaced by ``leaf(leaf_value)``.

    A container none of whose leaves changed (by identity) is returned as
    is; a changed mapping becomes a ``dict``, a sequence or set keeps its
    type, a named tuple its fields.
    """
    if isinstance(value, Mapping):
        return _rebuild_mapping(cast("Mapping[object, object]", value), leaf)
    if isinstance(value, (list, tuple, set, frozenset)):
        return _rebuild_collection(cast("list[object]", value), leaf)
    if isinstance(value, (str, bytes, int, float, type(None))):
        return leaf(value)
    names = _field_names(value)
    if not names:
        return leaf(value)
    return _rebuild_fields(value, names, leaf)


def _rebuild_mapping(mapping: Mapping[object, object], leaf: Callable[[object], object]) -> object:
    items = [(rebuild(k, leaf), rebuild(v, leaf)) for k, v in mapping.items()]
    if all(a is k and b is v for (a, b), (k, v) in zip(items, mapping.items(), strict=True)):
        return mapping
    return dict(items)


def _rebuild_collection(
    value: list[object] | tuple[object, ...] | set[object] | frozenset[object],
    leaf: Callable[[object], object],
) -> object:
    items = [rebuild(item, leaf) for item in value]
    if all(new is old for new, old in zip(items, value, strict=True)):
        return value
    if isinstance(value, tuple) and hasattr(value, "_fields"):  # a named tuple
        named = cast("Callable[..., object]", type(value))
        return named(*items)
    return cast("Callable[[list[object]], object]", type(value))(items)


def _rebuild_fields(
    value: object, names: tuple[str, ...], leaf: Callable[[object], object]
) -> object:
    changed = {
        name: new
        for name in names
        if (new := rebuild(old := cast("object", getattr(value, name)), leaf)) is not old
    }
    if not changed:
        return value
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return dataclasses.replace(value, **changed)
    if hasattr(type(value), "__struct_fields__"):
        structs = importlib.import_module("msgspec.structs")
        replace = cast("Callable[..., object]", structs.replace)
        return replace(value, **changed)
    copy = cast("Callable[..., object]", getattr(value, "model_copy"))  # noqa: B009 — a pydantic model, duck-typed.
    return copy(update=changed)
