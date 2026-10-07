"""Synthesizing a lazy ``ServiceLocator[T]`` injectable per collectable service type.

wireup builds ``Sequence[T]`` and ``Mapping[Hashable, T]`` collections for every
registered service type, eagerly, keyed by each member's qualifier. This module
mirrors that for :class:`~xtr_dependency_injection.runtime.service_locator.ServiceLocator`:
for each type the container provides — and each ``ServiceLocator[T]`` a definition's
provider asks for — it registers a factory building a
:class:`~xtr_dependency_injection.runtime.service_locator.ServiceLocator` whose keys
are exactly those ``Mapping[Hashable, T]`` would receive, but whose entries resolve
only when asked for by name.

Why a locator per type rather than one generic factory: wireup keys a service by
its full parameterized type, so ``ServiceLocator[Mailer]`` and
``ServiceLocator[Logger]`` are two distinct registrations, each with its own entry
set. Building them here — off the final definitions, alias forwards included — keeps
the entry keys in lock-step with the qualifiers wireup registers.

A locator resolves in the scope its consumer was built in. A locator over
singleton-only members is a singleton and holds the root container; one over any
scoped or transient member follows that lifetime and holds the scope's container,
built where its scoped consumer is. So a scoped consumer's locator resolves scoped
entries from its own scope, a singleton's from the root — and a singleton consumer
that asks for a scoped-membered locator is refused at build with the same scope
error wireup gives, exactly as for ``Mapping[Hashable, T]``.
"""

from __future__ import annotations

import inspect
import typing
from types import UnionType
from typing import TYPE_CHECKING, Annotated, Any, Final, cast, get_args, get_origin

import wireup
from wireup import AsyncContainer, ScopedAsyncContainer

from xtr_dependency_injection.exception._signatures import evaluated_signature
from xtr_dependency_injection.runtime.service_locator import ServiceLocator
from xtr_dependency_injection.runtime.wireup_container import WireupContainer

if TYPE_CHECKING:
    from collections.abc import Callable, Hashable, Iterator, Sequence

    from xtr_dependency_injection.builder.definition import Definition, Lifetime, ServiceKey

__all__ = ["service_locator_injectables"]

_MODULE = "xtr_dependency_injection.runtime"

_TYPING_UNION: Final = typing.Union  # pyright: ignore[reportDeprecated] — not an annotation.
"""``Optional[T]``'s origin before Python 3.14 folds it into ``types.UnionType``."""


def service_locator_injectables(definitions: Sequence[Definition]) -> list[object]:
    """Return the wireup injectables realizing ``ServiceLocator[T]`` for every needed ``T``.

    A ``ServiceLocator[T]`` is synthesized for each type ``T`` the container
    provides (so its locator carries the same members ``Mapping[Hashable, T]``
    would) and for each ``T`` a definition's provider asks a
    ``ServiceLocator[T]`` for — the latter yielding an empty locator when no
    member is registered, where an empty ``Mapping[Hashable, T]`` is simply not
    injectable.

    A type is skipped when it is itself a ``ServiceLocator[...]`` (no locator of
    locators) or when a definition already provides its ``ServiceLocator[T]``
    (an application or bundle factory wins, as it does for any other key).

    Args:
        definitions: Every definition, in emission order — the qualifiers and
            lifetimes are read from them in that order.
    """
    members = _members(definitions)
    provided_locators = {key[0] for definition in definitions if _is_locator(key := definition.key)}
    wanted: dict[type, None] = dict.fromkeys(members)
    for requested in _requested_types(definitions):
        wanted.setdefault(requested, None)

    injectables: list[object] = []
    for service in wanted:
        locator_type = _locator_type(service)
        if get_origin(service) is ServiceLocator or locator_type in provided_locators:
            continue
        entries = tuple(
            (qualifier, (service, qualifier)) for qualifier, _ in members.get(service, ())
        )
        lifetime = _collection_lifetime([lifetime for _, lifetime in members.get(service, ())])
        injectables.append(_locator_injectable(service, locator_type, entries, lifetime))
    return injectables


def _locator_type(service: type) -> type:
    """Return the ``ServiceLocator[service]`` generic alias as a service key.

    Subscripts through an ``Any`` view of the class so the type checkers do not
    read a runtime variable as a type expression.
    """
    return cast("type", cast("Any", ServiceLocator)[service])


def _members(
    definitions: Sequence[Definition],
) -> dict[type, list[tuple[Hashable | None, Lifetime]]]:
    """Group the qualifier and lifetime of every real registration by its provided type.

    The order within a type is emission order — the order ``Mapping[Hashable, T]``
    keys come out in — because ``definitions`` is already sorted. A definition
    keyed under a ``ServiceLocator[...]`` is not a member of anything.
    """
    grouped: dict[type, list[tuple[Hashable | None, Lifetime]]] = {}
    for definition in definitions:
        provided, qualifier = definition.key
        if get_origin(provided) is ServiceLocator:
            continue
        grouped.setdefault(provided, []).append((qualifier, definition.lifetime))
    return grouped


def _requested_types(definitions: Sequence[Definition]) -> Iterator[type]:
    """Yield every ``T`` a definition's provider declares a ``ServiceLocator[T]`` parameter of.

    Only class and factory providers carry a signature to read; an instance has
    none. A signature that cannot be evaluated (an annotation not importable at
    runtime) is skipped: that definition fails elsewhere with a clearer error.
    """
    for definition in definitions:
        provider = _provider_callable(definition)
        if provider is None:
            continue
        try:
            signature = evaluated_signature(provider)
        except (NameError, TypeError, ValueError):
            continue
        for parameter in signature.parameters.values():
            yield from _service_locator_arguments(cast("object", parameter.annotation))


def _provider_callable(definition: Definition) -> Callable[..., object] | type | None:
    """Return the class or factory whose signature to read, or ``None`` for an instance."""
    if definition.kind == "instance":
        return None
    return cast("Callable[..., object] | type", definition.provider)


def _service_locator_arguments(annotation: object) -> Iterator[type]:
    """Yield the ``T`` of every ``ServiceLocator[T]`` reachable through ``annotation``.

    Looks through a union (``ServiceLocator[T] | None``) and an ``Annotated``
    wrapper (``Injected[ServiceLocator[T]]``); a non-``type`` argument — a bare
    or type-variable ``ServiceLocator`` — is not a concrete request.
    """
    for member in _union_members(annotation):
        inner = member
        if get_origin(inner) is Annotated:
            inner = cast("tuple[object, ...]", get_args(inner))[0]
        if get_origin(inner) is ServiceLocator:
            arguments = cast("tuple[object, ...]", get_args(inner))
            if arguments and isinstance(arguments[0], type):
                yield arguments[0]


def _union_members(annotation: object) -> tuple[object, ...]:
    """Return ``annotation``'s union members, or ``annotation`` itself when it is not one."""
    origin = get_origin(annotation)
    # ``X | None`` has the origin ``UnionType``; ``Optional[X]`` reads back as
    # ``typing.Union`` until Python 3.14 merges them — each matched by identity.
    if origin is UnionType or origin is _TYPING_UNION:
        return cast("tuple[object, ...]", get_args(annotation))
    return (annotation,)


def _is_locator(key: ServiceKey) -> bool:
    """Return whether ``key``'s provided type is a ``ServiceLocator[...]``."""
    return get_origin(key[0]) is ServiceLocator


def _collection_lifetime(lifetimes: Sequence[Lifetime]) -> Lifetime:
    """Return the lifetime a collection of members with ``lifetimes`` takes.

    The widest wins — a transient or scoped member makes the whole collection so,
    exactly as wireup decides a ``Mapping``'s lifetime — so a locator is built,
    and holds its container, where its narrowest member must be. An empty
    collection is a singleton.
    """
    if "transient" in lifetimes:
        return "transient"
    if "scoped" in lifetimes:
        return "scoped"
    return "singleton"


def _locator_injectable(
    service: type,
    locator_type: type,
    entries: tuple[tuple[Hashable | None, ServiceKey], ...],
    lifetime: Lifetime,
) -> object:
    """Return the wireup injectable for one ``ServiceLocator[service]``.

    The factory takes the container it is built with — the root container for a
    singleton locator, the scope's for a scoped or transient one, so its entries
    resolve where its consumer lives — and hands back a locator mapping each
    name to its ``(service, qualifier)`` key.
    """
    scoped = lifetime != "singleton"
    container_annotation: type = ScopedAsyncContainer if scoped else AsyncContainer
    mapping = dict(entries)

    def build(container: object) -> object:
        return ServiceLocator(WireupContainer(cast("AsyncContainer", container)), mapping)

    name = f"_service_locator_{service.__name__}"
    setattr(  # noqa: B010 — dunders read by wireup through inspect.signature.
        build,
        "__signature__",
        inspect.Signature(
            parameters=[
                inspect.Parameter(
                    "container", inspect.Parameter.KEYWORD_ONLY, annotation=container_annotation
                )
            ],
            return_annotation=locator_type,
        ),
    )
    build.__annotations__ = {"container": container_annotation, "return": locator_type}
    build.__module__ = _MODULE
    build.__name__ = name
    build.__qualname__ = name
    return cast("Callable[..., Any]", wireup.injectable(build, lifetime=lifetime))
