"""Turning every decorating definition into a decoration of its target.

Every definition carrying ``decorates`` — set by
``Definition.set_decorated_service`` or by
:class:`~xtr_dependency_injection.compiler.autowire_as_decorator_pass.AutowireAsDecoratorPass`
— becomes an entry in the build's decoration table, sorted so the highest
priority wraps the original first, and is removed from its own key so the
decorator lives only under the target's.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast, final

from xtr_dependency_injection.builder.definition import Definition, Origin
from xtr_dependency_injection.decorator.as_decorator import OnInvalid, decorated_parameter_of
from xtr_dependency_injection.exception import (
    DecoratorSignatureError,
    InvalidDefinitionError,
    UnknownServiceError,
)
from xtr_dependency_injection.exception._naming import key_name, qualified_name

from ._state import state_of
from .check_definition_validity_pass import invalid_arguments
from .priority_tagged_service import by_priority
from .registration import _null_decorator_factory
from .wireup_compiler import Decoration

if TYPE_CHECKING:
    from collections.abc import Callable

    from xtr_dependency_injection.builder.container_builder import ContainerBuilder
    from xtr_dependency_injection.builder.definition import Decorates
    from xtr_dependency_injection.decorator.as_decorator import DecoratedParameter

__all__ = ["DecoratorServicePass"]


@final
class DecoratorServicePass:
    """Resolves each decorating definition against its target.

    ``on_invalid`` chooses what happens when the target is not defined:

    - :attr:`OnInvalid.EXCEPTION` raises :class:`UnknownServiceError`;
    - :attr:`OnInvalid.IGNORE` drops the decorator silently;
    - :attr:`OnInvalid.NULL` keeps the decorator under the target key and
      injects ``None`` for its ``AutowireDecorated`` parameter (the
      annotation must be ``T | None``).
    """

    __slots__ = ()

    def process(self, builder: ContainerBuilder) -> None:
        """Record every decoration, highest priority first, and drop the decorators' own keys.

        Raises:
            UnknownServiceError: :attr:`OnInvalid.EXCEPTION` and target missing.
            InvalidDefinitionError: A decorator's arguments do not fit it.
            DecoratorSignatureError: The decorator has none, several, or one
                ``Annotated[..., AutowireDecorated()]`` parameter of the wrong
                type - or :attr:`OnInvalid.NULL` on a parameter that does not
                allow ``None``.
        """
        decorations = state_of(builder).decorations
        pending = [
            (order, definition, definition.decorates)
            for order, definition in enumerate(builder.get_definitions())
            if definition.decorates is not None
        ]
        ranked = by_priority(pending, priority=lambda p: p[2].priority, order=lambda p: p[0])
        for _, definition, decorates in ranked:
            target_type, target_qualifier = decorates.key
            builder.remove_definition(*definition.key)
            decorator = cast("type | Callable[..., object]", definition.provider)
            name = qualified_name(decorator)
            exists = builder.has_definition(target_type, target_qualifier)
            if not exists and decorates.on_invalid is OnInvalid.EXCEPTION:
                raise UnknownServiceError(decorates.key, "decorate")
            if not exists and decorates.on_invalid is OnInvalid.IGNORE:
                builder.log(self, f"Ignored {name}: {key_name(decorates.key)} is missing.")
                continue
            parameter = decorated_parameter_of(decorator, target_type)
            reason = invalid_arguments(decorator, definition.arguments, reserved=parameter.name)
            if reason is not None:
                raise InvalidDefinitionError(definition.key, reason)
            if exists:
                decorations.setdefault(decorates.key, []).append(
                    Decoration(decorator, parameter.name, name, definition.get_arguments())
                )
            else:
                _ = builder.set_definition(
                    _null_decorator(definition, decorates, decorator, parameter)
                )


def _null_decorator(
    definition: Definition,
    decorates: Decorates,
    decorator: type | Callable[..., object],
    parameter: DecoratedParameter,
) -> Definition:
    """Return ``decorator`` defined under its missing target, with ``None`` for the inner."""
    if not parameter.allows_none:
        raise DecoratorSignatureError(
            qualified_name(decorator),
            (
                "on_invalid=OnInvalid.NULL requires the AutowireDecorated parameter "
                f"{parameter.name!r} to allow None (annotate it as T | None)"
            ),
        )
    target_type, _ = decorates.key
    null = Definition(
        key=decorates.key,
        provider=_null_decorator_factory(decorator, parameter.name, target_type),
        kind="factory",
        lifetime="singleton",
        origin=Origin(
            definition.origin.kind,
            definition.origin.name,
            f"decorator of missing {qualified_name(target_type)}",
        ),
    )
    return null.set_arguments(definition.get_arguments())
