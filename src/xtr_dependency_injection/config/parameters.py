"""Values injected with ``Inject(config=...)``: ``@parameters`` and how they merge.

Parameters from the kernel, from bundles and from the application merge into
one nested mapping, which becomes wireup's ``config=``. They merge, never
override: a leaf set twice is an error naming both sources. Keys nest
because wireup reads dotted paths — ``Inject(config="kernel.environment")``
— so a key never contains a dot itself.
"""

from __future__ import annotations

import inspect
from collections.abc import Mapping
from typing import TYPE_CHECKING, Final, TypeVar, cast

from xtr_dependency_injection.decorator._marker import own_marker, set_marker
from xtr_dependency_injection.exception import ConfigProviderError, ParameterConflictError

from .config_provider import provider_name

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

__all__ = ["call_parameters", "is_parameters", "merge_parameters", "parameters"]

F = TypeVar("F", bound="Callable[..., object]")

_PARAMETERS: Final = "__xtr_parameters__"
_ABSENT: Final = object()


def parameters(fn: F, /) -> F:
    """Merge what the decorated ``def () -> Mapping[str, object]`` returns into the parameters."""
    return set_marker(fn, _PARAMETERS, True)  # noqa: FBT003 — a marker's value, not a flag argument.


def is_parameters(obj: object) -> bool:
    """Return whether ``@parameters`` was put on ``obj`` itself."""
    return own_marker(obj, _PARAMETERS) is True


def call_parameters(fn: Callable[..., object]) -> Mapping[str, object]:
    """Call a ``@parameters`` function and return what it provides.

    Raises:
        ConfigProviderError: If it takes arguments or does not return a
            mapping.
    """
    name = provider_name(fn)
    if inspect.signature(fn).parameters:
        raise ConfigProviderError(name, "a @parameters function takes no arguments")
    try:
        produced = fn()
    except Exception as error:
        error.add_note(f"raised by parameters provider {name}")
        raise
    if not isinstance(produced, Mapping):
        raise ConfigProviderError(name, f"returned {type(produced).__qualname__}, not a mapping")
    return cast("Mapping[str, object]", produced)


def merge_parameters(sources: Iterable[tuple[str, Mapping[str, object]]]) -> dict[str, object]:
    """Deep-merge ``(source name, values)`` pairs, in order, into one nested dict.

    Only mappings merge; anything else is a leaf.

    Raises:
        ConfigProviderError: If a key is not a string or contains a dot.
        ParameterConflictError: If two sources set the same leaf.
    """
    merged: dict[str, object] = {}
    owners: dict[tuple[str, ...], str] = {}
    for source, values in sources:
        _merge_into(merged, values, (), source, owners)
    return merged


def _merge_into(
    target: dict[str, object],
    values: Mapping[str, object],
    path: tuple[str, ...],
    source: str,
    owners: dict[tuple[str, ...], str],
) -> None:
    for key, value in values.items():
        if not isinstance(key, str) or "." in key:  # pyright: ignore[reportUnnecessaryIsInstance]
            raise ConfigProviderError(source, f"parameter key {key!r} must be a string without '.'")
        here = (*path, key)
        existing = target.get(key, _ABSENT)
        if isinstance(value, Mapping) and (existing is _ABSENT or isinstance(existing, dict)):
            nested = cast("dict[str, object]", existing) if existing is not _ABSENT else {}
            target[key] = nested
            _ = owners.setdefault(here, source)
            _merge_into(nested, cast("Mapping[str, object]", value), here, source, owners)
        elif existing is not _ABSENT:
            raise ParameterConflictError(here, owners[here], source)
        else:
            target[key] = value
            owners[here] = source
