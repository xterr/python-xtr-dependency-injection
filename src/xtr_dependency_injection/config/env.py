"""Reading an environment variable while the kernel builds: ``env()``.

Config functions run during ``build()``, so ``env()`` reads the environment
of the process building the container.

``env`` is overloaded so the return type follows ``cast`` and ``default``:
``env("PORT", int)`` is ``int``, ``env("PORT", int, default=None)`` is
``int | None``, and ``env("HOST")`` is ``str``.

``bool`` is the one ``cast`` that is not applied as ``bool(value)``. That would
be truthy for every non-empty string — ``bool("false")`` is ``True`` — which is
never what an environment flag means. So ``bool`` is special-cased: the value is
read as ``1/true/yes/on`` for true and ``0/false/no/off`` or empty for false,
case-insensitively, and anything else raises ``InvalidEnvironmentVariableError``.
"""

from __future__ import annotations

import os
from enum import Enum
from typing import TYPE_CHECKING, Final, TypeVar, overload

from xtr_dependency_injection.exception import (
    InvalidEnvironmentVariableError,
    MissingEnvironmentVariableError,
)

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ["MISSING", "Missing", "env"]

T = TypeVar("T")
D = TypeVar("D")

_TRUE: Final = frozenset({"1", "true", "yes", "on"})
_FALSE: Final = frozenset({"0", "false", "no", "off", ""})


class Missing(Enum):
    """The type of :data:`MISSING`: no default was given."""

    MISSING = "MISSING"


MISSING: Final = Missing.MISSING


@overload
def env(name: str, /) -> str: ...
@overload
def env(name: str, /, *, default: D) -> str | D: ...
@overload
def env(name: str, cast: Callable[[str], T], /) -> T: ...
@overload
def env(name: str, cast: Callable[[str], T], /, *, default: D) -> T | D: ...
def env(
    name: str,
    cast: Callable[[str], object] = str,
    /,
    *,
    default: object = MISSING,
) -> object:
    """Return the environment variable ``name``, converted by ``cast``.

    ``bool`` reads ``1/true/yes/on`` as true and ``0/false/no/off`` or an
    empty value as false, in any case — ``bool("false")`` would be true. A
    default is returned as given, not converted.

    Raises:
        MissingEnvironmentVariableError: If the variable is not set and no
            default was given.
        InvalidEnvironmentVariableError: If ``cast`` refuses the value.
    """
    value = os.environ.get(name)
    if value is None:
        if default is MISSING:
            raise MissingEnvironmentVariableError(name)
        return default
    if cast is bool:
        return _boolean(name, value)
    try:
        return cast(value)
    except (TypeError, ValueError) as error:
        raise InvalidEnvironmentVariableError(name, cast, value) from error


def _boolean(name: str, value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in _TRUE:
        return True
    if normalized in _FALSE:
        return False
    raise InvalidEnvironmentVariableError(name, bool, value)
