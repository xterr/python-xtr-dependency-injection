"""Our own parameter injection markers, compiled to the engine's before wireup sees them.

These mark parameters on any callable the kernel presents to the container
— a class constructor, a factory function, a hook, or a target of
:func:`bind_callable`::

    def __init__(
        self,
        env: Annotated[str, Autowire(param="kernel.environment")],
        smtp: Annotated[Mailer, Target("smtp")],
    ) -> None: ...


    async def warm(cache: Injected[Cache]) -> None: ...

``Injected[T]`` marks a parameter as container-provided — the default
autowiring, resolved by type. It is the alias
:data:`Annotated[T, Autowire()] <Injected>`. Users never import wireup's
markers; the compiler rewrites ours into wireup's before any signature is
presented to the engine.
"""

from __future__ import annotations

from collections.abc import Hashable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, TypeVar

if TYPE_CHECKING:
    from typing import TypeAlias

__all__ = ["Autowire", "Injected", "Target"]


@dataclass(frozen=True, slots=True)
class Autowire:
    """Mark a parameter as container-provided; :attr:`param` names a parameter to inject.

    Without :attr:`param`, the parameter is resolved by its type, like
    :data:`Injected`; with :attr:`param`, the named dotted parameter (such
    as ``kernel.name`` or ``kernel.environment``) is injected instead.

    Attributes:
        param: A dotted parameter name to inject, or ``None`` to resolve by
            type.
    """

    param: str | None = None


@dataclass(frozen=True, slots=True)
class Target:
    """Point a container-provided parameter at a specific qualifier.

    Names the qualifier the container should resolve for this parameter,
    when several services of one type live under different qualifiers.

    Attributes:
        name: The qualifier of the service to inject.
    """

    name: Hashable


T = TypeVar("T")

Injected: TypeAlias = Annotated[T, Autowire()]
"""Mark a parameter as container-provided, resolved by its type.

Alias of :data:`Annotated[T, Autowire()] <Autowire>` — the default
autowiring, resolved by the parameter's type annotation.
"""
