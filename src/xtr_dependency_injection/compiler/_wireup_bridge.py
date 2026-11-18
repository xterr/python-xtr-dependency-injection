"""The one place that reaches past wireup's public API.

wireup exposes no way to answer "is this type known" without side effects, nor
the rule it keys a factory by. The kernel needs both: the second to know the
key a factory will be registered under before wireup ever sees it, the first
to answer container queries without trying to build. Everything that depends
on wireup's internals lives here, so a wireup release that moves them breaks
this one module.

``REGISTRATION_ATTRIBUTE`` names the dunder ``@injectable`` writes on what it
decorates; the bridge exports the name so ``clone_function`` can strip it
when copying a factory, keeping the mark out of the clone.
"""

from __future__ import annotations

import inspect
from functools import reduce
from operator import or_
from types import UnionType
from typing import TYPE_CHECKING, Annotated, Any, cast, get_args, get_origin

import wireup
from wireup.ioc.registry import _function_get_unwrapped_return_type
from wireup.ioc.type_analysis import analyze_type

from xtr_dependency_injection.config.env_placeholder import env_parameter
from xtr_dependency_injection.decorator.autowire import Autowire, bare_service_locator
from xtr_dependency_injection.decorator.target import Target
from xtr_dependency_injection.exception import InvalidArgumentError, InvalidArgumentTypeError
from xtr_dependency_injection.exception._type_aliases import without_type_aliases

if TYPE_CHECKING:
    from collections.abc import Callable, Hashable, Mapping

    from wireup import AsyncContainer

    from xtr_dependency_injection.builder.definition import Definition

__all__ = [
    "REGISTRATION_ATTRIBUTE",
    "built_type",
    "is_registered",
    "key_type",
    "mark_bare_locator_injections",
    "parameter_injections",
    "parameters_of",
    "to_engine_signature",
]

REGISTRATION_ATTRIBUTE = "__wireup_registration__"
"""Where ``@injectable`` records its declaration on what it marks."""


def is_registered(container: AsyncContainer, service: type, qualifier: Hashable | None) -> bool:
    """Return whether ``container`` has a service registered for ``(service, qualifier)``.

    wireup exposes no public predicate for "is this type known"; ``container.get``
    only answers by trying to build. This is the one place that reaches into
    wireup's registry to answer without side effects.
    """
    # Wireup has no public predicate; see the docstring.
    return container._registry.is_type_with_qualifier_known(service, qualifier)  # noqa: SLF001 — no public predicate


def parameters_of(container: AsyncContainer) -> Mapping[str, object]:
    """Return every parameter ``container`` was created with, as given to ``config=``.

    wireup reads parameters one dotted name at a time and exposes no way to
    list them; its store keeps the mapping it was given.
    """
    store = cast("object", container.config)
    return cast("Mapping[str, object]", getattr(store, "_ConfigStore__bag"))  # noqa: B009 — the store's private mapping, see above.


def key_type(provider: Callable[..., object] | type) -> type:
    """Return the key type wireup would register ``provider`` under.

    The implementation type is what wireup registers ``provider`` under: a
    class is itself, a function is its return annotation evaluated against its
    module, a generator function is the type it yields. It is then normalized
    the way wireup normalizes it, so ``Annotated`` wrappers are stripped and an
    optional return stays ``T | None``. A ``type`` alias is read as what it
    stands for — the clone the engine registers carries the same expanded
    return (see ``clone_function``), so both agree on the key.

    Raises:
        InvalidArgumentTypeError: If ``provider`` is a function without a
            return annotation.
    """
    implementation = cast("object | None", _function_get_unwrapped_return_type(provider))
    if implementation is None:
        implementation = _aliased_yield_type(provider)
    if implementation is None:
        name = getattr(provider, "__qualname__", repr(provider))
        reason = f"factory {name} must annotate its return type: that is the service it provides"
        raise InvalidArgumentTypeError(reason)
    return analyze_type(without_type_aliases(implementation)).normalized_type


def _aliased_yield_type(provider: Callable[..., object] | type) -> object | None:
    """Return what a generator factory yields when its return is an alias of the iterator.

    wireup reads the yielded type off the return's arguments, and an alias —
    ``type Sessions = Iterator[Session]`` — has none until expanded.
    """
    if isinstance(provider, type) or not (
        inspect.isgeneratorfunction(provider) or inspect.isasyncgenfunction(provider)
    ):
        return None
    returned: object = inspect.signature(provider, eval_str=True).return_annotation
    arguments = cast("tuple[object, ...]", get_args(without_type_aliases(returned)))
    return arguments[0] if arguments else None


def to_engine_signature(signature: inspect.Signature) -> inspect.Signature:
    """Return ``signature`` with our ``Autowire``/``Target`` markers rewritten to wireup's.

    A parameter annotated ``Annotated[T, Autowire()]`` becomes
    ``Annotated[T, wireup.Inject()]``, ``Autowire(param=p)`` becomes
    ``wireup.Inject(config=p)``, ``Autowire(env=e)`` becomes an injection of
    the placeholder for ``e`` (resolved by the caller, see
    :func:`parameter_injections`), and ``Target(n)`` becomes
    ``wireup.Inject(qualifier=n)``. Any other metadata (including a
    ``wireup.Inject`` a user wrote directly) is left untouched, so a user
    reaching for the engine still works.

    A signature without any of our markers is returned unchanged, so this
    helper is safe to apply on every callable presented to wireup.

    A marker on a member of a union — ``Injected[T] | None`` — is rewritten in
    place: the engine reads ``Annotated`` through an optional the same way.
    """
    parameters = list(signature.parameters.values())
    changed = False
    for index, parameter in enumerate(parameters):
        rewritten = _rewrite_annotation(cast("object", parameter.annotation))
        if rewritten is not None:
            parameters[index] = parameter.replace(annotation=rewritten)
            changed = True
    if not changed:
        return signature
    return signature.replace(parameters=parameters)


def _rewrite_annotation(annotation: object) -> object | None:
    """Return a rewritten ``Annotated[...]`` or ``None`` when nothing changed."""
    if get_origin(annotation) is UnionType:
        members = cast("tuple[object, ...]", get_args(annotation))
        rewritten = [_rewrite_annotation(member) for member in members]
        if all(member is None for member in rewritten):
            return None
        merged = [
            new if new is not None else old for new, old in zip(rewritten, members, strict=True)
        ]
        return reduce(or_, merged)
    if get_origin(annotation) is not Annotated:
        return None
    wrapped, *metadata = cast("tuple[object, ...]", get_args(annotation))
    metadata = _merge_target(metadata)
    new_metadata: list[object] = []
    changed = False
    for entry in metadata:
        translated = _translate(entry)
        if translated is entry:
            new_metadata.append(entry)
        else:
            new_metadata.append(translated)
            changed = True
    if not changed:
        return None
    annotated: Any = Annotated
    return cast("object", annotated[(wrapped, *new_metadata)])


def _merge_target(metadata: list[object]) -> list[object]:
    """Let ``Target(q)`` carry the injection when a plain ``Autowire()`` sits beside it.

    ``Annotated[T, Autowire(), Target("q")]`` means one thing — the service ``T``
    qualified ``q`` — so it becomes one engine marker, not two the engine refuses.

    Raises:
        ValueError: If ``Target`` sits beside ``Autowire(param=...)`` or
            ``Autowire(env=...)``: a parameter is injected from a parameter, from the
            environment, or as a qualified service — never two of them.
    """
    targets = [entry for entry in metadata if isinstance(entry, Target)]
    autowires = [entry for entry in metadata if isinstance(entry, Autowire)]
    if not targets or not autowires:
        return metadata
    if any(entry.param is not None or entry.env is not None for entry in autowires):
        msg = (
            "Target(...) cannot be combined with Autowire(param=...) or Autowire(env=...): "
            "a parameter is injected from a parameter, from the environment, or as a "
            "qualified service"
        )
        raise InvalidArgumentError(msg)
    return [entry for entry in metadata if not isinstance(entry, Autowire)]


def mark_bare_locator_injections(signature: inspect.Signature) -> inspect.Signature:
    """Return ``signature`` with every bare ``ServiceLocator[T]`` parameter given an ``Autowire()``.

    The engine fills only marked parameters when injecting into a bound callable
    — a command, a handler, a hook — so a bare ``ServiceLocator[T]`` there needs
    a marker a class or factory would not. Marking it with ``Autowire()`` before
    :func:`to_engine_signature` runs lets the same rewrite carry it to the
    engine, and leaves a signature without one untouched.
    """
    parameters = list(signature.parameters.values())
    changed = False
    for index, parameter in enumerate(parameters):
        if bare_service_locator(cast("object", parameter.annotation)):
            annotated: Any = Annotated
            wrapped = cast("object", annotated[(parameter.annotation, Autowire())])
            parameters[index] = parameter.replace(annotation=wrapped)
            changed = True
    if not changed:
        return signature
    return signature.replace(parameters=parameters)


def parameter_injections(signature: inspect.Signature) -> tuple[str, ...]:
    """Return the names of the parameters injected from a parameter or the environment.

    Those are the arguments that may carry an environment placeholder, which
    the caller resolves before calling what ``signature`` belongs to.
    """
    return tuple(
        parameter.name
        for parameter in signature.parameters.values()
        if any(
            isinstance(entry, Autowire) and (entry.param is not None or entry.env is not None)
            for entry in _metadata(cast("object", parameter.annotation))
        )
    )


def _metadata(annotation: object) -> tuple[object, ...]:
    if get_origin(annotation) is UnionType:
        members = cast("tuple[object, ...]", get_args(annotation))
        return tuple(entry for member in members for entry in _metadata(member))
    if get_origin(annotation) is not Annotated:
        return ()
    return cast("tuple[object, ...]", get_args(annotation))[1:]


def _translate(entry: object) -> object:
    """Translate one of our markers to wireup's; return ``entry`` unchanged otherwise."""
    if isinstance(entry, Autowire):
        if entry.env is not None:
            return wireup.Inject(config=env_parameter(entry.env))
        return wireup.Inject(config=entry.param) if entry.param is not None else wireup.Inject()
    if isinstance(entry, Target):
        return wireup.Inject(qualifier=entry.name)
    return entry


def built_type(definition: Definition) -> type | None:
    """Return the concrete type ``definition``'s provider builds, or ``None`` when unknown.

    - ``class``: the provider itself.
    - ``instance``: ``type(provider)``.
    - ``factory``: ``key_type(provider)``, or ``None`` when the factory
      has no return annotation (autoconfigure tag rules skip those).

    A parameterized generic (``ServiceLocator[T]``) is unwrapped to its origin
    class so ``__mro__`` walks succeed, and an optional return (``T | None``)
    to its single non-``None`` member, which is the type the factory builds.
    """
    kind = definition.kind
    provider = definition.provider
    if kind == "class":
        return cast("type", provider)
    if kind == "instance":
        return type(provider)
    try:
        key = key_type(cast("Callable[..., object]", provider))
    except InvalidArgumentTypeError:
        return None
    unwrapped = _non_optional(key)
    origin = get_origin(unwrapped)
    if isinstance(origin, type):
        return origin
    return cast("type", unwrapped)


def _non_optional(annotation: object) -> object:
    """Return ``annotation``'s single non-``None`` member, or ``annotation`` unchanged.

    ``T | None`` and ``Optional[T]`` both read back as :data:`types.UnionType`.
    """
    origin = get_origin(annotation)
    if origin is UnionType:
        members = [arg for arg in get_args(annotation) if arg is not type(None)]
        if len(members) == 1:
            return members[0]
    return annotation
