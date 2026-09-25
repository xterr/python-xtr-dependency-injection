"""Wrapping a service with another that takes its place: ``@as_decorator`` and ``Inner[T]``.

The decorator is registered under the decorated service's key, so everything
asking for that service — and every ``Sequence[T]`` holding it — gets the
decorator. The decorator receives the original through its one ``Inner[T]``
parameter::

    @as_decorator(MessageBusInterface)
    class TracingBus:
        def __init__(self, inner: Inner[MessageBusInterface], tracer: Tracer) -> None: ...
"""

from __future__ import annotations

import inspect
from collections.abc import Hashable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Final, TypeAlias, TypeVar, cast, get_args, get_origin

from xtr_dependency_injection.exception import DecoratorSignatureError

from ._marker import own_marker, set_marker

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = [
    "DecoratorMarker",
    "Inner",
    "InnerMarker",
    "as_decorator",
    "decorator_of",
    "inner_parameter_of",
    "inner_type_of",
]

T = TypeVar("T")
D = TypeVar("D", bound="Callable[..., object]")

_DECORATOR: Final = "__xtr_decorator__"


@dataclass(frozen=True, slots=True)
class InnerMarker:
    """Marks the parameter of a decorator that receives the decorated service."""


Inner: TypeAlias = Annotated[T, InnerMarker()]
"""The decorated service, as a decorator's parameter: ``inner: Inner[MessageBusInterface]``."""


@dataclass(frozen=True, slots=True)
class DecoratorMarker:
    """What ``@as_decorator`` records: the service decorated, and the decoration's order."""

    target: type
    qualifier: Hashable | None = None
    priority: int = 0


def as_decorator(
    target: type, /, *, qualifier: Hashable | None = None, priority: int = 0
) -> Callable[[D], D]:
    """Decorate the service ``(target, qualifier)`` with the decorated class or factory.

    Decorations of one service apply by ``priority``, highest first: the
    highest wraps the original, and each next one wraps the previous result.
    The decorator gets the decorated service's lifetime.
    """

    def decorate(decorator: D) -> D:
        return set_marker(decorator, _DECORATOR, DecoratorMarker(target, qualifier, priority))

    return decorate


def decorator_of(obj: object) -> DecoratorMarker | None:
    """Return what ``@as_decorator`` recorded on ``obj``, or ``None``."""
    return cast("DecoratorMarker | None", own_marker(obj, _DECORATOR))


def inner_type_of(annotation: object) -> object | None:
    """Return ``T`` when ``annotation`` is ``Inner[T]``, else ``None``."""
    if get_origin(annotation) is not Annotated:
        return None
    wrapped, *metadata = cast("tuple[object, ...]", get_args(annotation))
    return wrapped if any(isinstance(entry, InnerMarker) for entry in metadata) else None


def inner_parameter_of(decorator: object, target: object) -> str:
    """Return the name of ``decorator``'s one ``Inner[target]`` parameter.

    Raises:
        DecoratorSignatureError: If it has none, several, or one of another
            type than ``target``.
    """
    name = f"{getattr(decorator, '__module__', '?')}:{getattr(decorator, '__qualname__', '?')}"
    hint = "import annotation types at runtime, not under TYPE_CHECKING"
    try:
        signature = inspect.signature(cast("Callable[..., object]", decorator), eval_str=True)
    except NameError as error:
        error.add_note(f"while reading decorator {name}: {hint}")
        raise
    inner = [
        (parameter.name, inner_type_of(cast("object", parameter.annotation)))
        for parameter in signature.parameters.values()
    ]
    found = [(parameter, inner_type) for parameter, inner_type in inner if inner_type is not None]
    if len(found) != 1:
        reason = f"it must have exactly one Inner[...] parameter, not {len(found)}"
        raise DecoratorSignatureError(name, reason)
    ((parameter, inner_type),) = found
    if inner_type is not target:
        reason = f"its Inner[...] parameter {parameter!r} must be of the decorated type"
        raise DecoratorSignatureError(name, reason)
    return parameter
