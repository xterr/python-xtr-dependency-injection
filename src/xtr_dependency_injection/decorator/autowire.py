"""Our own parameter injection markers, compiled to the engine's before wireup sees them.

These mark parameters on any callable the kernel presents to the container
— a class constructor, a factory function, a hook, or a target of
:func:`bind_callable`::

    def __init__(
        self,
        env: Annotated[str, Autowire(param="kernel.environment")],
        port: Annotated[int, Autowire(env="int:SMTP_PORT")],
        smtp: Annotated[Mailer, Target("smtp")],
    ) -> None: ...


    async def warm(cache: Injected[Cache]) -> None: ...

:class:`~xtr_dependency_injection.decorator.target.Target` picks a qualified
service; it lives in its own module.

``Injected[T]`` marks a parameter as container-provided — the default
autowiring, resolved by type. It is the alias
:data:`Annotated[T, Autowire()] <Injected>`. Users never import wireup's
markers; the compiler rewrites ours into wireup's before any signature is
presented to the engine.
"""

from __future__ import annotations

import typing
from dataclasses import dataclass
from types import UnionType
from typing import TYPE_CHECKING, Annotated, Final, TypeVar, cast, get_args, get_origin

from xtr_dependency_injection.exception import InvalidArgumentError

from ._dependency_base import DependencyBase, set_dependency
from .target import Target

if TYPE_CHECKING:
    from typing import TypeAlias

__all__ = ["Autowire", "Injected", "is_container_supplied"]

_TYPING_UNION: Final = typing.Union  # pyright: ignore[reportDeprecated] — not an annotation.
"""``Optional[T]``'s origin before Python 3.14 folds it into ``types.UnionType``."""


@dataclass(frozen=True, slots=True, init=False)
class Autowire(DependencyBase):
    """Mark a parameter as container-provided — by type, by parameter, or from the environment.

    Without :attr:`param` or :attr:`env`, the parameter is resolved by its
    type, like :data:`Injected`. With :attr:`param`, the named dotted
    parameter (such as ``kernel.name``) is injected, any environment
    placeholder in it resolved. With :attr:`env`, the environment variable
    expression (``"int:PORT"``, ``"json:file:SECRETS"``) is read when the
    service is built, through the container's processors.

    When the web framework is installed the marker is also one of its
    dependency declarations, so the same annotation resolves through the
    container inside a route; ``**fastapi`` exists for the framework's own
    copy of a marker and is never written by hand.

    Attributes:
        param: A dotted parameter name to inject.
        env: An environment variable expression to inject.

    Raises:
        ValueError: If both :attr:`param` and :attr:`env` are given.
    """

    param: str | None = None
    env: str | None = None

    def __init__(
        self,
        param: str | None = None,
        env: str | None = None,
        **fastapi: object,
    ) -> None:
        """Record what to inject; refuse naming both a parameter and a variable."""
        if param is not None and env is not None:
            msg = "Autowire takes param= or env=, not both"
            raise InvalidArgumentError(msg)
        object.__setattr__(self, "param", param)
        object.__setattr__(self, "env", env)
        set_dependency(self, fastapi, param=param, env=env)


T = TypeVar("T")

Injected: TypeAlias = Annotated[T, Autowire()]
"""Mark a parameter as container-provided, resolved by its type.

Alias of :data:`Annotated[T, Autowire()] <Autowire>` — the default
autowiring, resolved by the parameter's type annotation.
"""


def is_container_supplied(annotation: object) -> bool:
    """Return whether the container fills a parameter annotated ``annotation``.

    True for ``Injected[T]``, ``Annotated[T, Autowire(...)]`` and
    ``Annotated[T, Target(...)]`` — also as a member of a union, such as
    ``Injected[T] | None``. Also true for a bare ``ServiceLocator[T]``, which the
    container fills with a lazy name-keyed map of the services of ``T`` without a
    marker, the way it fills a bare ``Sequence[T]`` or ``Mapping[Hashable, T]``. A
    library that calls a user's callable — a command, a message handler — asks
    this to tell the parameters it passes itself from the ones the container
    fills, so every such library agrees on what a marker is.
    """
    return any(
        _marks_injection(member) or _is_service_locator(member)
        for member in _union_members(annotation)
    )


def _union_members(annotation: object) -> tuple[object, ...]:
    """Return what ``annotation`` may be: its members if a union, else itself.

    ``X | None`` has the origin ``UnionType``; ``Optional[X]`` has ``typing.Union``
    until Python 3.14 makes them one, each matched by identity.
    """
    origin = get_origin(annotation)
    if origin is UnionType or origin is _TYPING_UNION:
        return cast("tuple[object, ...]", get_args(annotation))
    return (annotation,)


def _marks_injection(annotation: object) -> bool:
    if get_origin(annotation) is not Annotated:
        return False
    metadata = cast("tuple[object, ...]", get_args(annotation))[1:]
    return any(isinstance(entry, (Autowire, Target)) for entry in metadata)


def _is_service_locator(annotation: object) -> bool:
    """Return whether ``annotation`` is a ``ServiceLocator[T]``, ``Annotated`` wrapper aside.

    The container fills such a parameter without a marker; ``ServiceLocator`` is
    imported here, lazily, to keep the decorator layer free of a runtime import.
    """
    from xtr_dependency_injection.runtime.service_locator import (  # noqa: PLC0415 — avoid an import cycle
        ServiceLocator,
    )

    inner = annotation
    if get_origin(inner) is Annotated:
        inner = cast("tuple[object, ...]", get_args(inner))[0]
    return inner is ServiceLocator or get_origin(inner) is ServiceLocator


def bare_service_locator(annotation: object) -> bool:
    """Return whether the container fills ``annotation`` as an unmarked ``ServiceLocator[T]``.

    True for a bare ``ServiceLocator[T]`` — one no ``Autowire`` or ``Target``
    names — and false once a marker does, since the engine-signature rewrite
    already carries those. A caller that injects into a bound callable marks a
    bare locator itself, because the engine fills only marked parameters there.
    """
    members = _union_members(annotation)
    return any(_is_service_locator(member) for member in members) and not any(
        _marks_injection(member) for member in members
    )
