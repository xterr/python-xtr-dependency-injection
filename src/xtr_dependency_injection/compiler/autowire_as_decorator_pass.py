"""Turning every scanned ``@as_decorator`` into a definition that decorates its target.

A scanned decorator becomes a definition carrying ``decorates``, the same shape
``Definition.set_decorated_service`` gives one a bundle registers, so
:class:`~xtr_dependency_injection.compiler.decorator_service_pass.DecoratorServicePass`
reads decorations from one source. The definition lives under a private
qualifier: a factory decorator returns the decorated type itself, and must not
claim the decorated service's key before the decoration is resolved.
"""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Literal, cast, final

from xtr_dependency_injection.builder._origins import scanned_origin
from xtr_dependency_injection.builder.definition import Definition
from xtr_dependency_injection.decorator.as_decorator import decorator_of

from ._state import state_of
from ._wireup_bridge import key_type

if TYPE_CHECKING:
    from collections.abc import Callable

    from xtr_dependency_injection.builder.container_builder import ContainerBuilder

__all__ = ["AutowireAsDecoratorPass"]


@final
class AutowireAsDecoratorPass:
    """Registers each scanned ``@as_decorator`` as a definition decorating its target."""

    __slots__ = ()

    def process(self, builder: ContainerBuilder) -> None:
        """Add a decorating definition for every scanned decorator, in scan order."""
        for scanned in state_of(builder).scanned_decorators:
            marker = decorator_of(scanned.obj)
            if marker is None:  # pragma: no cover — the scanner queues only marked objects.
                continue
            provider = cast("type | Callable[..., object]", scanned.obj)
            kind: Literal["class", "factory"]
            if inspect.isclass(provider):
                provided, kind = provider, "class"
            else:
                provided, kind = key_type(provider), "factory"
            definition = Definition(
                key=(provided, f".decorator.{scanned.name}"),
                provider=provider,
                kind=kind,
                lifetime="singleton",
                origin=scanned_origin(scanned, "decorator"),
            ).set_decorated_service(
                marker.target,
                qualifier=marker.qualifier,
                priority=marker.priority,
                on_invalid=marker.on_invalid,
            )
            _ = builder.set_definition(definition)
