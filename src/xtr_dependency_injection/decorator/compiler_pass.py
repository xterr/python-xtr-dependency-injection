"""Letting the application adjust the whole container before it is compiled."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, TypeVar, cast, overload

from xtr_dependency_injection.builder.pass_stage import PassStage

from ._marker import own_marker, set_marker

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ["CompilerPassMarker", "compiler_pass", "compiler_pass_of"]

F = TypeVar("F", bound="Callable[..., object]")

_ATTRIBUTE: Final = "__xtr_compiler_pass__"


@dataclass(frozen=True, slots=True)
class CompilerPassMarker:
    """What ``@compiler_pass`` records: which stage it runs in and at what priority."""

    priority: int = 0
    stage: PassStage = PassStage.BEFORE_OPTIMIZATION


@overload
def compiler_pass(fn: F, /) -> F: ...
@overload
def compiler_pass(
    *, stage: PassStage = PassStage.BEFORE_OPTIMIZATION, priority: int = 0
) -> Callable[[F], F]: ...
def compiler_pass(
    fn: F | None = None,
    /,
    *,
    stage: PassStage = PassStage.BEFORE_OPTIMIZATION,
    priority: int = 0,
) -> F | Callable[[F], F]:
    """Run the decorated ``def (builder: ContainerBuilder) -> None`` in ``stage``.

    Passes run stage by stage in Symfony's order (see
    :class:`~xtr_dependency_injection.builder.pass_stage.PassStage`); within
    one stage, by ``priority`` descending, ties by scan order.
    """

    def record(target: F) -> F:
        return set_marker(target, _ATTRIBUTE, CompilerPassMarker(priority, stage))

    return record(fn) if fn is not None else record


def compiler_pass_of(obj: object) -> CompilerPassMarker | None:
    """Return what ``@compiler_pass`` recorded on ``obj``, or ``None``."""
    return cast("CompilerPassMarker | None", own_marker(obj, _ATTRIBUTE))
