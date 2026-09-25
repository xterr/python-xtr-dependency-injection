"""The one place that reaches past wireup's public API.

wireup exposes no way to read what ``@injectable`` recorded on an object, nor
the rule it keys a factory by. The kernel needs both: the first to adopt what
an application marked, the second to know the key a factory will be
registered under before wireup ever sees it. Everything that depends on
wireup's internals lives here, so a wireup release that moves them breaks one
module — and ``tests/contract`` says which behaviour moved.
"""

from __future__ import annotations

import inspect
from collections.abc import Hashable
from dataclasses import dataclass
from types import FunctionType
from typing import TYPE_CHECKING, Literal, cast

from wireup.errors import FactoryReturnTypeIsEmptyError
from wireup.ioc.registry import _function_get_unwrapped_return_type
from wireup.ioc.type_analysis import analyze_type

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = [
    "REGISTRATION_ATTRIBUTE",
    "declaration_of",
    "key_type",
    "provided_type",
    "unwrapped_return_type",
]

REGISTRATION_ATTRIBUTE = "__wireup_registration__"
"""Where ``@injectable`` records its declaration on what it marks."""


@dataclass(frozen=True, slots=True)
class _Declaration:
    """What ``@injectable`` recorded on an object, read into a stable shape."""

    obj: object
    qualifier: Hashable | None
    lifetime: Literal["singleton", "scoped", "transient"]
    as_type: type | None


def declaration_of(obj: object) -> _Declaration | None:
    """Return what ``@injectable`` recorded on ``obj``, or ``None``.

    Only functions and classes are asked, as wireup's own discovery does: a
    proxy object may answer ``hasattr`` with side effects. A registration is
    only ``obj``'s own when it points back at ``obj``: a subclass of a marked
    class inherits the attribute, and must not be mistaken for a second
    declaration of its parent. The deprecated ``@abstract`` marker records no
    lifetime and is not a declaration.
    """
    if not (isinstance(obj, FunctionType) or inspect.isclass(obj)):
        return None
    registration = cast("object", getattr(obj, REGISTRATION_ATTRIBUTE, None))
    if registration is None or getattr(registration, "obj", None) is not obj:
        return None
    if not hasattr(registration, "lifetime"):
        return None
    return _Declaration(
        obj=obj,
        qualifier=cast("Hashable | None", getattr(registration, "qualifier", None)),
        lifetime=cast(
            "Literal['singleton', 'scoped', 'transient']", getattr(registration, "lifetime", None)
        ),
        as_type=cast("type | None", getattr(registration, "as_type", None)),
    )


def unwrapped_return_type(provider: Callable[..., object] | type) -> object | None:
    """Return the type wireup would register ``provider`` under, or ``None``.

    A class is itself; a function is its return annotation, evaluated against
    its module; a generator function is the type it yields.
    """
    return cast("object | None", _function_get_unwrapped_return_type(provider))


def provided_type(declaration: _Declaration) -> type:
    """Return the key type wireup registers ``declaration`` under.

    That is ``as_type`` when given, else the class or the factory's return
    type — normalized the way wireup normalizes it, so ``Annotated`` wrappers
    are stripped and an optional return stays ``T | None``.

    Raises:
        FactoryReturnTypeIsEmptyError: If the declared function has no
            return annotation.
    """
    return key_type(cast("Callable[..., object] | type", declaration.obj), declaration.as_type)


def key_type(provider: Callable[..., object] | type, as_type: type | None) -> type:
    """Return the key type wireup would register ``provider`` under, given ``as_type``.

    Raises:
        FactoryReturnTypeIsEmptyError: If ``provider`` is a function without a
            return annotation.
    """
    implementation = unwrapped_return_type(provider)
    if implementation is None:
        raise FactoryReturnTypeIsEmptyError(provider)
    analysis = analyze_type(implementation)
    if as_type is None:
        return analysis.normalized_type
    target: object = as_type
    if analysis.is_optional:
        target = as_type | None
    return analyze_type(target).normalized_type
