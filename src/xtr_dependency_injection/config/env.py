"""Standing for an environment variable in a config or parameter: ``env()``.

``env()`` returns a placeholder; the variable is read when a service needing
it is built, by the container's environment variable processors (see
:mod:`~xtr_dependency_injection.config.env_placeholder`). Two spellings, one
mechanism:

- ``env("PORT", int)`` — typed: the cast becomes the processor prefix it
  stands for (``int``, ``float``, ``bool``, ``str``, or an ``Enum`` class),
  and any other callable is applied to the processed value.
- ``env("json:file:SECRETS")`` — a processor chain, read right to left:
  ``file`` reads the file ``SECRETS`` names, ``json`` decodes it.

``env`` is overloaded so the declared type follows ``cast`` and ``default``:
``env("PORT", int)`` is an ``int``, ``env("PORT", int, default=None)`` is
``int | None``, ``env("HOST")`` is a ``str``. ``default`` is returned when
the variable is not set, and is also the value a numeric placeholder carries
while the kernel builds, so validation sees a plausible number.
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, TypeVar, overload

from .env_placeholder import MISSING, Missing, placeholder

if TYPE_CHECKING:
    from collections.abc import Callable

    from typing_extensions import TypeIs

__all__ = ["MISSING", "Missing", "env"]

T = TypeVar("T")
D = TypeVar("D")

_PREFIX_OF: dict[object, str] = {str: "string", int: "int", float: "float", bool: "bool"}


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
    converter: Callable[[str], object] | None = None,
    /,
    *,
    default: object = MISSING,
) -> object:
    """Return a placeholder for the environment variable ``name``, read when it is needed.

    ``name`` may carry processor prefixes (``"json:file:SECRETS"``). A
    ``cast`` of ``int``, ``float``, ``bool``, ``str`` or an ``Enum`` class
    adds the matching prefix; any other callable is applied to the value the
    processors produce.
    """
    if converter is None:
        return placeholder(name, default=default)
    prefix = _PREFIX_OF.get(converter)
    if prefix is None and _is_enum(converter):
        prefix = f"enum:{converter.__module__}.{converter.__qualname__}"
    if prefix is not None:
        expression = name if prefix == "string" else f"{prefix}:{name}"
        return placeholder(expression, default=default)
    return placeholder(name, converter, default)


def _is_enum(converter: object) -> TypeIs[type[Enum]]:
    return isinstance(converter, type) and issubclass(converter, Enum)
