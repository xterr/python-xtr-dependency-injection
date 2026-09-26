"""Emitting the final definitions as wireup injectables, and building the container.

The order of what is emitted is the order of wireup's ``Sequence[T]`` and
``Mapping`` collections — a tagged-iterator priority: the kernel bundle,
then bundles in dependency order, then the application; within each, by
priority, highest first, then in declaration order.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from itertools import count
from typing import TYPE_CHECKING, cast

import wireup
from wireup.errors import WireupError

from xtr_dependency_injection.config.env_placeholder import env_placeholders_in
from xtr_dependency_injection.exception import ContainerCompilationError
from xtr_dependency_injection.exception._naming import key_name, qualified_name

from ._wireup_bridge import key_type
from .before_after_sorter import sort_with_priorities
from .registration import (
    _box_type,
    _clone_function,
    _decorating_factory,
    _env_resolving_factory,
    _map_result,
    _resolving_instance_factory,
    _synthesize_class_factory,
)
from .resettable_service_pass import RESET_TAG

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from wireup import AsyncContainer

    from xtr_dependency_injection.builder.definition import Definition, ServiceKey

__all__ = ["Decoration", "compile_container", "emission_order", "emit_injectables"]


@dataclass(frozen=True, slots=True)
class Decoration:
    """A validated decoration: the decorator, and which of its parameters is the inner service."""

    decorator: type | Callable[..., object]
    inner_parameter: str
    name: str
    arguments: Mapping[str, object] = field(default_factory=dict)


def emission_order(definitions: Sequence[Definition]) -> list[Definition]:
    """Return ``definitions`` in emission order.

    Order = wireup ``Sequence[T]``/``Mapping[Hashable, T]`` order. The seed is
    definition order; :func:`sort_with_priorities` reorders it
    by each definition's ``priority`` (highest first, ``None`` bounded by its
    ``before``/``after``) and by ``before``/``after`` constraints. Items are
    identified by their built type's ``module:qualname``.

    Args:
        definitions: Every definition, in declaration order.
    """
    identifiers: list[str] = [_identifier(index, d) for index, d in enumerate(definitions)]
    by_identifier: dict[str, Definition] = dict(zip(identifiers, definitions, strict=True))
    type_to_identifiers: dict[type, list[str]] = {}
    for identifier, definition in by_identifier.items():
        type_to_identifiers.setdefault(definition.key[0], []).append(identifier)

    priorities: dict[str, int | None] = {
        identifier: by_identifier[identifier].priority for identifier in identifiers
    }
    constraints: dict[str, dict[str, list[str]]] = {}
    for identifier, definition in by_identifier.items():
        entry: dict[str, list[str]] = {}
        if definition.before:
            entry["before"] = [qualified_name(target) for target in definition.before]
        if definition.after:
            entry["after"] = [qualified_name(target) for target in definition.after]
        if entry:
            constraints[identifier] = entry
    aliases: dict[str, list[str]] = {
        qualified_name(built): list(ids) for built, ids in type_to_identifiers.items()
    }

    ordered = sort_with_priorities(priorities, constraints, aliases)
    return [by_identifier[identifier] for identifier in ordered]


def _identifier(index: int, definition: Definition) -> str:
    """Return a stable, unique identifier for ``definition`` for the sorter.

    Base is the built type's ``module:qualname``; the ``index`` disambiguates
    two definitions built under the same type but different qualifiers.
    """
    provided, qualifier = definition.key
    base = qualified_name(provided)
    if qualifier is None:
        return f"{base}#{index}"
    return f"{base}[{qualifier!r}]#{index}"


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
        ContainerCompilationError: The engine refused to compile the
            container; ``__cause__`` is the wireup error, with a note naming
            the origin of every definition whose type the message mentions. An
            unknown-dependency failure is reworded to name the fix.
    """
    try:
        return wireup.create_async_container(
            injectables=injectables,
            config=parameters,
            concurrent_scoped_access=concurrent_scoped_access,
        )
    except WireupError as error:
        _note_origins(error, definitions)
        wrapped = ContainerCompilationError(_compilation_reason(error))
        for note in getattr(error, "__notes__", ()):
            wrapped.add_note(note)
        raise wrapped from error


def _emit(
    definition: Definition,
    decorations: Sequence[Decoration],
    track: Callable[[object, str], None],
    boxes: Iterator[int],
) -> list[object]:
    """Return the injectables realizing ``definition``: one, or a box per decoration plus one."""
    provided, qualifier = definition.key
    lifetime = definition.lifetime
    hook = _reset_hook(definition)
    if not decorations and hook is None:
        as_is = _as_is(definition)
        if as_is is not None:
            return [as_is]
    factory, implementation = _factory_for(
        definition.provider, instance=definition.kind == "instance", arguments=definition.arguments
    )
    if hook is not None:
        tracked = _tracking(track, hook)
        factory = _map_result(factory, tracked, provides=implementation)
    emitted: list[object] = []
    for decoration in decorations:
        box = _box_type(next(boxes))
        boxed = _map_result(factory, box, provides=box)
        emitted.append(wireup.injectable(boxed, lifetime=lifetime))
        decorator, implementation = _factory_for(
            decoration.decorator, instance=False, arguments=decoration.arguments
        )
        factory = _decorating_factory(
            decorator, decoration.inner_parameter, box, provides=implementation
        )
    emitted.append(
        wireup.injectable(
            factory,
            lifetime=lifetime,
            qualifier=qualifier,
            as_type=provided if provided is not implementation else None,
        )
    )
    return emitted


def _reset_hook(definition: Definition) -> str | None:
    """Return the ``method`` attribute of the first ``kernel.reset`` tag, else ``None``.

    The ``kernel.reset`` tag carries the method name the ``ServicesResetter``
    calls on a service; ``ResettableServicePass`` has checked it is a string.
    """
    tags = definition.get_tag(RESET_TAG)
    return cast("str", tags[0]["method"]) if tags else None


def _as_is(definition: Definition) -> object | None:
    """Return what to emit for ``definition`` without a factory of ours, when possible.

    An instance goes through ``wireup.instance``; every other kind needs a
    factory synthesized by :func:`_factory_for`.
    """
    provided, qualifier = definition.key
    if definition.kind == "instance" and not env_placeholders_in(definition.provider):
        return wireup.instance(definition.provider, qualifier=qualifier, as_type=provided)
    return None


def _factory_for(
    provider: object, *, instance: bool, arguments: Mapping[str, object]
) -> tuple[Callable[..., object], type]:
    """Return a factory for ``provider``, and the type it produces.

    For an instance we lean on ``wireup.instance``: the returned factory is a
    marked function, but ``_map_result`` / ``_decorating_factory`` wrap it
    into an unmarked clone, and the outer ``wireup.injectable`` call re-marks
    that clone with the definition's key. So the marker never surfaces. An
    instance holding environment placeholders gets a factory resolving them
    instead; a class or function with ``Autowire(param=/env=)`` parameters a
    factory resolving those arguments before the call.
    """
    if instance:
        implementation = type(provider)
        if env_placeholders_in(provider):
            return _resolving_instance_factory(provider), implementation
        return wireup.instance(provider, as_type=implementation), implementation
    if isinstance(provider, type):
        factory = _synthesize_class_factory(provider)
        resolving = _env_resolving_factory(
            provider, factory, provides=provider, arguments=arguments
        )
        return resolving, provider
    function = cast("Callable[..., object]", provider)
    implementation = key_type(function)
    factory = _env_resolving_factory(
        function, _clone_function(function), provides=implementation, arguments=arguments
    )
    return factory, implementation


def _tracking(track: Callable[[object, str], None], method: str) -> Callable[[object], object]:
    def tracked(value: object) -> object:
        track(value, method)
        return value

    return tracked


def _note_origins(error: WireupError, definitions: Sequence[Definition]) -> None:
    """Note where every definition the engine's message mentions came from.

    The engine names a class by its dotted path and a factory by its
    qualified name (ours are named after what they build); a bare class name
    would also match an unrelated class of that name from another module.
    """
    message = str(error)
    for definition in definitions:
        provided = definition.key[0]
        module = getattr(provided, "__module__", None)
        qualname = getattr(provided, "__qualname__", None)
        if not (isinstance(module, str) and isinstance(qualname, str)):
            continue
        if f"{module}.{qualname}" in message or f"<function {qualname} at " in message:
            error.add_note(f"{key_name(definition.key)} is defined by {definition.origin}")


_UNKNOWN_DEPENDENCY_PATTERN = (
    r"^Parameter '(?P<param>.+?)' of (?P<owner>.+?) has an unknown dependency on "
    r"(?P<dependency>.+?)(?: with qualifier '(?P<qualifier>.+?)')?\.$"
)
_UNKNOWN_DEPENDENCY = re.compile(_UNKNOWN_DEPENDENCY_PATTERN)
"""wireup's unknown-dependency message (a bare ``WireupError`` with no typed data)."""

_ENGINE_CLASS = re.compile(r"<class '(?P<path>[^']+)'>")


def _compilation_reason(error: WireupError) -> str:
    """Return our own message for an unknown-dependency failure, else the engine's.

    wireup raises a bare ``WireupError`` whose only data is a formatted string,
    so the shape is matched with a regex; anything that does not match keeps the
    engine's message verbatim. The engine error stays reachable as ``__cause__``.
    """
    match = _UNKNOWN_DEPENDENCY.match(str(error))
    if match is None:
        return str(error)
    owner = _engine_readable(match.group("owner"))
    dependency = _engine_readable(match.group("dependency"))
    qualifier = match.group("qualifier")
    needed = f"{dependency}[{qualifier!r}]" if qualifier is not None else dependency
    return (
        f"{owner}.{match.group('param')} needs {needed}, which is not a registered "
        f"service: mark it @as_service (or alias it with @as_alias), or register it "
        f"in a bundle's load_extension"
    )


def _engine_readable(token: str) -> str:
    """Turn a ``repr(cls)`` such as ``<class 'a.B'>`` into its dotted path."""
    match = _ENGINE_CLASS.fullmatch(token)
    return match.group("path") if match else token
