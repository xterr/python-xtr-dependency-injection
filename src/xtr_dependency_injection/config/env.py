"""Reading an environment variable while the kernel builds: ``env()``.

Config functions run during ``build()``, so ``env()`` reads the environment
of the process building the container — the Python-first counterpart of
Symfony's ``%env(X)%``.
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

_TRUE: Final = frozenset({"1", "true", "yes", "on"})
_FALSE: Final = frozenset({"0", "false", "no", "off", ""})


class Missing(Enum):
    """The type of :data:`MISSING`: no default was given."""

    MISSING = "MISSING"


MISSING: Final = Missing.MISSING


@overload
def env(name: str, /, *, default: str | Missing = MISSING) -> str: ...
@overload
def env(name: str, cast: Callable[[str], T], /, *, default: T | Missing = MISSING) -> T: ...
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
