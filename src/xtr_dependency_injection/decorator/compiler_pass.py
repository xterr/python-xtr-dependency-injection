"""Letting the application adjust the whole container before it is compiled."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, TypeVar, cast, overload

from ._marker import own_marker, set_marker

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ["CompilerPassMarker", "compiler_pass", "compiler_pass_of"]

F = TypeVar("F", bound="Callable[..., object]")

_ATTRIBUTE: Final = "__xtr_compiler_pass__"


@dataclass(frozen=True, slots=True)
class CompilerPassMarker:
    """What ``@compiler_pass`` records: its order among the application's passes."""

    priority: int = 0


@overload
def compiler_pass(fn: F, /) -> F: ...
@overload
def compiler_pass(*, priority: int = 0) -> Callable[[F], F]: ...
def compiler_pass(fn: F | None = None, /, *, priority: int = 0) -> F | Callable[[F], F]:
    """Run the decorated ``def (builder: ContainerBuilder) -> None`` after the bundles' ``process``.

    Passes run by ``priority``, highest first, then in scan order.
    """

    def decorate(target: F) -> F:
        return set_marker(target, _ATTRIBUTE, CompilerPassMarker(priority))

    return decorate(fn) if fn is not None else decorate


def compiler_pass_of(obj: object) -> CompilerPassMarker | None:
    """Return what ``@compiler_pass`` recorded on ``obj``, or ``None``."""
    return cast("CompilerPassMarker | None", own_marker(obj, _ATTRIBUTE))
