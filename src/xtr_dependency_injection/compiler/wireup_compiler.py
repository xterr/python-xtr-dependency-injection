"""Emitting the final definitions as wireup injectables, and building the container.

The order of what is emitted is the order of wireup's ``Sequence[T]`` and
``Mapping`` collections — Symfony's tagged-iterator priority: the kernel
bundle, then bundles in dependency order, then the application; within each,
by priority, highest first, then in declaration order.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from itertools import count
from typing import TYPE_CHECKING, cast

import wireup
from wireup.errors import WireupError

from xtr_dependency_injection.exception._naming import key_name

from ._wireup_bridge import declaration_of, key_type
from .registration import (
    _box_type,
    _clone_function,
    _decorating_factory,
    _instance_factory,
    _map_result,
    _synthesize_class_factory,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

    from wireup import AsyncContainer

    from xtr_dependency_injection.builder.definition import Definition, Origin, ServiceKey

__all__ = ["Decoration", "compile_container", "emission_order", "emit_injectables"]


@dataclass(frozen=True, slots=True)
class Decoration:
    """A validated decoration: the decorator, and which of its parameters is the inner service."""

    decorator: type | Callable[..., object]
    inner_parameter: str
    name: str


def emission_order(definitions: Sequence[Definition], bundles: Sequence[str]) -> list[Definition]:
    """Return ``definitions`` in emission order.

    Args:
        definitions: Every definition, in declaration order.
        bundles: Active bundle names, in dependency order.
    """
    position = {name: index for index, name in enumerate(bundles)}

    def group(origin: Origin) -> int:
        if origin.kind == "kernel":
            return 0
        if origin.kind == "bundle":
            return 1 + position.get(origin.name, len(bundles))
        return 2 + len(bundles)

    return sorted(definitions, key=lambda d: (group(d.origin), -d.priority))


def emit_injectables(
    definitions: Sequence[Definition],
    decorations: Mapping[ServiceKey, Sequence[Decoration]],
    track: Callable[[object, str], None],
) -> list[object]:
    """Return the wireup injectables realizing ``definitions``, already in emission order.

    Args:
        definitions: What to emit, in order.
        decorations: Per key, the decorations to apply, outermost last.
        track: Called with every built instance of a resettable service and
            its reset method.
    """
    boxes = count(1)
    injectables: list[object] = []
    for definition in definitions:
        injectables.extend(_emit(definition, decorations.get(definition.key, ()), track, boxes))
    return injectables


def compile_container(
    injectables: list[object],
    definitions: Sequence[Definition],
    /,
    *,
    parameters: dict[str, object],
    concurrent_scoped_access: bool,
) -> AsyncContainer:
    """Build the wireup container from ``injectables``.

    Args:
        injectables: What :func:`emit_injectables` returned.
        definitions: The definitions they realize, to name origins in errors.
        parameters: wireup's ``config=``.
        concurrent_scoped_access: Passed to wireup.

    Raises:
        WireupError: Unchanged from wireup, with a note naming the origin of
            every definition whose type the message mentions.
    """
    try:
        return wireup.create_async_container(
            injectables=injectables,
            config=parameters,
            concurrent_scoped_access=concurrent_scoped_access,
        )
    except WireupError as error:
        _note_origins(error, definitions)
        raise


def _emit(
    definition: Definition,
    decorations: Sequence[Decoration],
    track: Callable[[object, str], None],
    boxes: Iterator[int],
) -> list[object]:
    """Return the injectables realizing ``definition``: one, or a box per decoration plus one."""
    provided, qualifier = definition.key
    lifetime = definition.lifetime
    if not decorations and definition.reset_method is None:
        as_is = _as_is(definition)
        if as_is is not None:
            return [as_is]
    factory, implementation = _factory_for(
        definition.provider, instance=definition.kind == "instance"
    )
    if definition.reset_method is not None:
        tracked = _tracking(track, definition.reset_method)
        factory = _map_result(factory, tracked, provides=implementation)
    emitted: list[object] = []
    for decoration in decorations:
        box = _box_type(next(boxes))
        boxed = _map_result(factory, box, provides=box)
        emitted.append(wireup.injectable(boxed, lifetime=lifetime))
        decorator, implementation = _factory_for(decoration.decorator, instance=False)
        factory = _decorating_factory(
            decorator, decoration.inner_parameter, box, provides=implementation
        )
    as_type = None if provided is implementation else provided
    emitted.append(
        wireup.injectable(factory, lifetime=lifetime, as_type=as_type, qualifier=qualifier)
    )
    return emitted


def _as_is(definition: Definition) -> object | None:
    """Return what to emit for ``definition`` without a factory of ours, when possible.

    A declared object is emitted as marked when its mark agrees with the
    definition; an instance goes through ``wireup.instance``.
    """
    provided, qualifier = definition.key
    if definition.kind == "instance":
        return wireup.instance(definition.provider, as_type=provided, qualifier=qualifier)
    if definition.kind != "declared":
        return None
    declaration = declaration_of(definition.provider)
    if declaration is None:
        return None
    provider = cast("Callable[..., object] | type", definition.provider)
    agrees = (
        key_type(provider, declaration.as_type) is provided
        and declaration.qualifier == qualifier
        and declaration.lifetime == definition.lifetime
    )
    return definition.provider if agrees else None


def _factory_for(provider: object, *, instance: bool) -> tuple[Callable[..., object], type]:
    """Return an unmarked factory for ``provider``, and the type it produces."""
    if instance:
        return _instance_factory(provider), type(provider)
    if isinstance(provider, type):
        return _synthesize_class_factory(provider), provider
    function = cast("Callable[..., object]", provider)
    return _clone_function(function), key_type(function, None)


def _tracking(track: Callable[[object, str], None], method: str) -> Callable[[object], object]:
    def tracked(value: object) -> object:
        track(value, method)
        return value

    return tracked


def _note_origins(error: WireupError, definitions: Sequence[Definition]) -> None:
    message = str(error)
    for definition in definitions:
        name = getattr(definition.key[0], "__name__", None)
        if isinstance(name, str) and name in message:
            error.add_note(f"{key_name(definition.key)} is defined by {definition.origin}")
