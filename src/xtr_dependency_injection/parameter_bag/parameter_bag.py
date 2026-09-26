"""Parameters by dotted name, and the ``%name%`` references between them.

A string anywhere in a parameter — or in a bundle config resolved against
the bag — may reference a parameter between percent signs:

- ``"%kernel.project_dir%"`` alone is the parameter's own value, whatever
  its type;
- ``"%kernel.project_dir%/var/log"`` embeds it, which only a string or a
  number can be;
- ``"100%%"`` is a literal percent sign, kept escaped by resolution and
  turned back into ``%`` by :meth:`ParameterBag.unescape_value`.

A referenced parameter's own references are resolved too; a reference back
to a parameter being resolved is a loop.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import TYPE_CHECKING, Final, cast

from typing_extensions import override

from xtr_dependency_injection.config._walk import rebuild
from xtr_dependency_injection.config.env_placeholder import EnvPlaceholder
from xtr_dependency_injection.exception import (
    InvalidParameterTypeError,
    ParameterCircularReferenceError,
    ParameterNotFoundError,
)

from .parameter_bag_interface import ParameterBagInterface

__all__ = ["ParameterBag"]

_WHOLE: Final = re.compile(r"%([^%\s]+)%")
_ANY: Final = re.compile(r"%%|%([^%\s]+)%")
_MISSING: Final = object()

if TYPE_CHECKING:
    from collections.abc import MutableMapping


class ParameterBag(ParameterBagInterface):
    """Holds parameters, nested by dotted name, and resolves references against them."""

    __slots__: tuple[str, ...] = ("_parameters", "_resolved")

    _parameters: dict[str, object]
    _resolved: bool

    def __init__(self, parameters: Mapping[str, object] | None = None) -> None:
        """Start with ``parameters``, or none."""
        self._parameters = {}
        self._resolved = False
        if parameters is not None:
            self.add(parameters)

    @override
    def clear(self) -> None:
        self._parameters.clear()

    @override
    def add(self, parameters: Mapping[str, object], /) -> None:
        _merge(self._parameters, parameters)

    @override
    def all(self) -> dict[str, object]:
        return dict(self._parameters)

    @override
    def get(self, name: str, /) -> object:
        current: object = self._parameters
        for part in name.split("."):
            if not isinstance(current, Mapping):
                raise ParameterNotFoundError(name)
            current = cast("Mapping[str, object]", current).get(part, _MISSING)
            if current is _MISSING:
                raise ParameterNotFoundError(name)
        return current

    @override
    def remove(self, name: str, /) -> None:
        *parents, leaf = name.split(".")
        holder = self._holder(parents, create=False)
        if holder is not None:
            _ = holder.pop(leaf, None)

    @override
    def set(self, name: str, value: object, /) -> None:
        *parents, leaf = name.split(".")
        holder = self._holder(parents, create=True)
        if holder is not None:
            holder[leaf] = value

    @override
    def has(self, name: str, /) -> bool:
        try:
            _ = self.get(name)
        except ParameterNotFoundError:
            return False
        return True

    @override
    def resolve(self) -> None:
        if self._resolved:
            return
        self._parameters = cast("dict[str, object]", self._resolve(self._parameters, ()))
        self._resolved = True

    def is_resolved(self) -> bool:
        """Return whether :meth:`resolve` has run."""
        return self._resolved

    @override
    def resolve_value(self, value: object, /) -> object:
        """Return ``value`` with every reference in its strings resolved; untouched parts kept.

        ``%%`` stays escaped; :meth:`unescape_value` turns it into ``%``.

        Raises:
            ParameterNotFoundError: If a reference names no parameter.
            ParameterCircularReferenceError: If references loop.
            InvalidParameterTypeError: If an embedded reference names
                something other than a string or a number.
        """
        return self._resolve(value, ())

    def resolve_string(self, value: str, /) -> object:
        """Return ``value`` resolved — the referenced value itself when it is one whole reference.

        Raises:
            ParameterNotFoundError: If a reference names no parameter.
            ParameterCircularReferenceError: If references loop.
            InvalidParameterTypeError: If an embedded reference names
                something other than a string or a number.
        """
        return self._resolve_string(value, ())

    @override
    def escape_value(self, value: object, /) -> object:
        return rebuild(value, lambda leaf: _replace(leaf, "%", "%%"))

    @override
    def unescape_value(self, value: object, /) -> object:
        return rebuild(value, lambda leaf: _replace(leaf, "%%", "%"))

    def _resolve(self, value: object, resolving: tuple[str, ...]) -> object:
        def leaf(item: object) -> object:
            if isinstance(item, str) and not isinstance(item, EnvPlaceholder):
                return self._resolve_string(item, resolving)
            return item

        return rebuild(value, leaf)

    def _resolve_string(self, value: str, resolving: tuple[str, ...]) -> object:
        if "%" not in value:
            return value
        whole = _WHOLE.fullmatch(value)
        if whole is not None:
            return self._reference(whole.group(1), resolving)

        def embed(match: re.Match[str]) -> str:
            name = match.group(1)
            if name is None:
                return "%%"
            resolved = self._reference(name, resolving)
            if isinstance(resolved, EnvPlaceholder):
                return str(resolved)
            if isinstance(resolved, bool) or not isinstance(resolved, (str, int, float)):
                raise InvalidParameterTypeError(name, type(resolved).__qualname__, value)
            return str(resolved)

        resolved = _ANY.sub(embed, value)
        return value if resolved == value else resolved

    def _reference(self, name: str, resolving: tuple[str, ...]) -> object:
        if name in resolving:
            raise ParameterCircularReferenceError((*resolving[resolving.index(name) :], name))
        value = self.get(name)
        if self._resolved:
            return value
        return self._resolve(value, (*resolving, name))

    def _holder(self, parents: list[str], *, create: bool) -> MutableMapping[str, object] | None:
        holder: MutableMapping[str, object] = self._parameters
        for part in parents:
            child = holder.get(part)
            if not isinstance(child, dict):
                if not create:
                    return None
                child = {}
                holder[part] = child
            holder = cast("MutableMapping[str, object]", child)
        return holder


def _merge(into: dict[str, object], values: Mapping[str, object]) -> None:
    for key, value in values.items():
        existing = into.get(key)
        if isinstance(value, Mapping) and isinstance(existing, dict):
            _merge(cast("dict[str, object]", existing), cast("Mapping[str, object]", value))
        elif isinstance(value, Mapping):
            nested: dict[str, object] = {}
            _merge(nested, cast("Mapping[str, object]", value))
            into[key] = nested
        else:
            into[key] = value


def _replace(leaf: object, old: str, new: str) -> object:
    if isinstance(leaf, str) and not isinstance(leaf, EnvPlaceholder) and old in leaf:
        return leaf.replace(old, new)
    return leaf
