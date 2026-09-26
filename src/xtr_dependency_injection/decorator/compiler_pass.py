"""Letting the application adjust the whole container before it is compiled."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, TypeVar, cast, overload

from xtr_dependency_injection.compiler.compiler_pass_interface import CompilerPassInterface
from xtr_dependency_injection.compiler.pass_stage import PassStage

from ._marker import own_marker, set_marker

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ["CompilerPassMarker", "compiler_pass", "compiler_pass_of"]

P = TypeVar("P", bound=type[CompilerPassInterface])

_ATTRIBUTE: Final = "__xtr_compiler_pass__"


@dataclass(frozen=True, slots=True)
class CompilerPassMarker:
    """What ``@compiler_pass`` records: which stage it runs in and at what priority."""

    priority: int = 0
    stage: PassStage = PassStage.BEFORE_OPTIMIZATION


@overload
def compiler_pass(cls: P, /) -> P: ...
@overload
def compiler_pass(
    *, stage: PassStage = PassStage.BEFORE_OPTIMIZATION, priority: int = 0
) -> Callable[[P], P]: ...
def compiler_pass(
    cls: P | None = None,
    /,
    *,
    stage: PassStage = PassStage.BEFORE_OPTIMIZATION,
    priority: int = 0,
) -> P | Callable[[P], P]:
    """Run the decorated :class:`CompilerPassInterface` class in ``stage`` at ``priority``.

    The kernel builds the class with no arguments when it prepares the
    container, after every bundle's ``build``. Passes run stage by stage (see
    :class:`PassStage`); within one stage by ``priority`` descending, ties by
    registration order.

    Raises:
        TypeError: If the decorated object is not a class implementing
            :class:`CompilerPassInterface`.
    """

    def record(target: P) -> P:
        if not (isinstance(target, type) and issubclass(target, CompilerPassInterface)):  # pyright: ignore[reportUnnecessaryIsInstance] — callers outside the type checker.
            msg = f"@compiler_pass needs a class implementing CompilerPassInterface, not {target!r}"  # pyright: ignore[reportUnreachable]
            raise TypeError(msg)
        return set_marker(target, _ATTRIBUTE, CompilerPassMarker(priority, stage))

    return record(cls) if cls is not None else record


def compiler_pass_of(obj: object) -> CompilerPassMarker | None:
    """Return what ``@compiler_pass`` recorded on ``obj``, or ``None``."""
    return cast("CompilerPassMarker | None", own_marker(obj, _ATTRIBUTE))
