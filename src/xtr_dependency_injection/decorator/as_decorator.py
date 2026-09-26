"""Decoration: ``@as_decorator`` records a target, ``AutowireDecorated`` marks the inner parameter.

The decorator is registered under the decorated service's key, so everything
asking for that service - and every ``Sequence[T]`` holding it - gets the
decorator. The decorator receives the original through its one parameter
annotated ``Annotated[T, AutowireDecorated()]``::

    @as_decorator(MessageBusInterface)
    class TracingBus:
        def __init__(
            self,
            inner: Annotated[MessageBusInterface, AutowireDecorated()],
            tracer: Tracer,
        ) -> None: ...

When the decorated service is missing, the ``on_invalid`` option decides:
``OnInvalid.EXCEPTION`` (the default) fails the build;
``OnInvalid.IGNORE`` drops the decorator; ``OnInvalid.NULL`` keeps the
decorator under the missing target's key with ``None`` for its
``AutowireDecorated`` parameter (which must then allow ``None``).
"""

from __future__ import annotations

import inspect
import types
from collections.abc import Hashable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Final, TypeVar, cast, get_args, get_origin

from xtr_dependency_injection.builder.on_invalid import OnInvalid
from xtr_dependency_injection.exception import DecoratorSignatureError
from xtr_dependency_injection.exception._naming import qualified_name
from xtr_dependency_injection.exception._signatures import evaluated_signature

from ._marker import own_marker, set_marker

_UNION_ORIGINS: Final = frozenset({get_origin(int | type(None)), types.UnionType})

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = [
    "AutowireDecorated",
    "DecoratedParameter",
    "DecoratorMarker",
    "OnInvalid",
    "as_decorator",
    "decorated_parameter_of",
    "decorator_of",
]

D = TypeVar("D", bound="Callable[..., object]")

_DECORATOR: Final = "__xtr_decorator__"


@dataclass(frozen=True, slots=True)
class AutowireDecorated:
    """Marks the parameter of a decorator that receives the decorated service.

    Applied through ``Annotated[T, AutowireDecorated()]`` to the parameter
    that receives the service the decorator wraps.
    """


@dataclass(frozen=True, slots=True)
class DecoratorMarker:
    """What ``@as_decorator`` records on a class or factory function.

    Attributes:
        target: The type of the decorated service.
        qualifier: The qualifier of the decorated service, or ``None``.
        priority: Order among decorators of the same target - highest first.
        on_invalid: Behavior when the target is not defined.
    """

    target: type
    qualifier: Hashable | None = None
    priority: int = 0
    on_invalid: OnInvalid = OnInvalid.EXCEPTION


def as_decorator(
    target: type,
    /,
    *,
    qualifier: Hashable | None = None,
    priority: int = 0,
    on_invalid: OnInvalid = OnInvalid.EXCEPTION,
) -> Callable[[D], D]:
    """Register the decorated class or factory as a decorator of ``(target, qualifier)``.

    Decorations of one service apply by ``priority``, highest first: the
    highest wraps the original, and each next one wraps the previous result.
    The decorator inherits the decorated service's lifetime and lives only
    under the target's key.

    ``on_invalid`` chooses what happens when the target is not defined.
    """

    def record(target_obj: D) -> D:
        return set_marker(
            target_obj,
            _DECORATOR,
            DecoratorMarker(target, qualifier, priority, on_invalid),
        )

    return record


def decorator_of(obj: object) -> DecoratorMarker | None:
    """Return what ``@as_decorator`` recorded on ``obj``, or ``None``."""
    return cast("DecoratorMarker | None", own_marker(obj, _DECORATOR))


@dataclass(frozen=True, slots=True)
class DecoratedParameter:
    """The parameter of a decorator that receives the decorated service.

    Attributes:
        name: The parameter name.
        allows_none: Whether its annotation is ``T | None`` -
            :attr:`OnInvalid.NULL` needs it to be true.
    """

    name: str
    allows_none: bool


def decorated_parameter_of(decorator: object, target: object) -> DecoratedParameter:
    """Return which parameter of ``decorator`` carries ``Annotated[target, AutowireDecorated()]``.

    ``target`` may equally match ``target | None`` (``Optional[target]``);
    :attr:`DecoratedParameter.allows_none` reports which case was found. The
    ``OnInvalid.NULL`` code path requires it to be true.

    Raises:
        DecoratorSignatureError: If ``decorator`` has none, several, or one
            parameter annotated for another type than ``target``, or a
            positional-only one.
    """
    name = qualified_name(decorator)
    signature = evaluated_signature(
        cast("Callable[..., object]", decorator), context=f"reading decorator {name}"
    )
    found: list[tuple[str, object, bool]] = []
    for parameter in signature.parameters.values():
        typed = _autowire_decorated_type(cast("object", parameter.annotation))
        if typed is not None:
            inner_type, allows_none = typed
            found.append((parameter.name, inner_type, allows_none))
    if len(found) != 1:
        reason = (
            f"it must have exactly one Annotated[..., AutowireDecorated()] "
            f"parameter, not {len(found)}"
        )
        raise DecoratorSignatureError(name, reason)
    parameter_name, inner_type, allows_none = found[0]
    if signature.parameters[parameter_name].kind is inspect.Parameter.POSITIONAL_ONLY:
        reason = (
            f"its Annotated[..., AutowireDecorated()] parameter {parameter_name!r} "
            "is positional-only; the decorated service is passed by keyword"
        )
        raise DecoratorSignatureError(name, reason)
    if inner_type is not target:
        reason = (
            f"its Annotated[..., AutowireDecorated()] parameter {parameter_name!r} "
            f"must be of the decorated type"
        )
        raise DecoratorSignatureError(name, reason)
    return DecoratedParameter(name=parameter_name, allows_none=allows_none)


def _autowire_decorated_type(annotation: object) -> tuple[object, bool] | None:
    """Return ``(T, allows_none)`` when ``annotation`` is ``Annotated[T, AutowireDecorated()]``.

    ``allows_none`` is true when ``T`` is ``X | None`` / ``Optional[X]``: the
    parameter can then be filled with ``None`` when the decorated service is
    missing and :attr:`OnInvalid.NULL` is chosen. Any other annotation
    returns ``None``.
    """
    if get_origin(annotation) is not Annotated:
        return None
    wrapped, *metadata = cast("tuple[object, ...]", get_args(annotation))
    if not any(isinstance(entry, AutowireDecorated) for entry in metadata):
        return None
    return _strip_none(wrapped)


def _strip_none(annotation: object) -> tuple[object, bool]:
    """Return ``(T, allows_none)`` for ``T``, ``T | None`` or ``Optional[T]``."""
    origin = get_origin(annotation)
    if origin in _UNION_ORIGINS:
        args = cast("tuple[object, ...]", get_args(annotation))
        non_none = tuple(arg for arg in args if arg is not type(None))
        if len(non_none) == 1 and len(non_none) != len(args):
            return non_none[0], True
    return annotation, False
