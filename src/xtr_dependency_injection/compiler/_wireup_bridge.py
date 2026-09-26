"""The one place that reaches past wireup's public API.

wireup exposes no way to answer "is this type known" without side effects, nor
the rule it keys a factory by. The kernel needs both: the second to know the
key a factory will be registered under before wireup ever sees it, the first
to answer container queries without trying to build. Everything that depends
on wireup's internals lives here, so a wireup release that moves them breaks
one module — and ``tests/contract`` says which behaviour moved.

``REGISTRATION_ATTRIBUTE`` names the dunder ``@injectable`` writes on what it
decorates; the bridge exports the name so ``_clone_function`` can strip it
when copying a factory, keeping the mark out of the clone.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any, cast, get_args, get_origin

import wireup
from wireup.errors import FactoryReturnTypeIsEmptyError
from wireup.ioc.registry import _function_get_unwrapped_return_type
from wireup.ioc.type_analysis import analyze_type

from xtr_dependency_injection.decorator.autowire import Autowire, Target

if TYPE_CHECKING:
    import inspect
    from collections.abc import Callable, Hashable

    from wireup import AsyncContainer

    from xtr_dependency_injection.builder.definition import Definition

__all__ = [
    "REGISTRATION_ATTRIBUTE",
    "built_type",
    "is_registered",
    "key_type",
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
    return container._registry.is_type_with_qualifier_known(service, qualifier)  # noqa: SLF001


def key_type(provider: Callable[..., object] | type, as_type: type | None) -> type:
    """Return the key type wireup would register ``provider`` under, given ``as_type``.

    The implementation type is what wireup registers ``provider`` under: a
    class is itself, a function is its return annotation evaluated against its
    module, a generator function is the type it yields. It is then normalized
    the way wireup normalizes it, so ``Annotated`` wrappers are stripped and an
    optional return stays ``T | None``.

    Raises:
        FactoryReturnTypeIsEmptyError: If ``provider`` is a function without a
            return annotation.
    """
    implementation = cast("object | None", _function_get_unwrapped_return_type(provider))
    if implementation is None:
        raise FactoryReturnTypeIsEmptyError(provider)
    analysis = analyze_type(implementation)
    if as_type is None:
        return analysis.normalized_type
    target: object = as_type
    if analysis.is_optional:
        target = as_type | None
    return analyze_type(target).normalized_type


def to_engine_signature(signature: inspect.Signature) -> inspect.Signature:
    """Return ``signature`` with our ``Autowire``/``Target`` markers rewritten to wireup's.

    A parameter annotated ``Annotated[T, Autowire()]`` becomes
    ``Annotated[T, wireup.Inject()]``, ``Autowire(param=p)`` becomes
    ``wireup.Inject(config=p)``, and ``Target(n)`` becomes
    ``wireup.Inject(qualifier=n)``. Any other metadata (including a
    ``wireup.Inject`` a user wrote directly) is left untouched, so a user
    reaching for the engine still works — see the interop tests.

    A signature without any of our markers is returned unchanged, so this
    helper is safe to apply on every callable presented to wireup.
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
    if get_origin(annotation) is not Annotated:
        return None
    wrapped, *metadata = cast("tuple[object, ...]", get_args(annotation))
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


def _translate(entry: object) -> object:
    """Translate one of our markers to wireup's; return ``entry`` unchanged otherwise."""
    if isinstance(entry, Autowire):
        return wireup.Inject(config=entry.param) if entry.param is not None else wireup.Inject()
    if isinstance(entry, Target):
        return wireup.Inject(qualifier=entry.name)
    return entry


def built_type(definition: Definition) -> type | None:
    """Return the concrete type ``definition``'s provider builds, or ``None`` when unknown.

    - ``class``: the provider itself.
    - ``instance``: ``type(provider)``.
    - ``factory``: ``key_type(provider, None)``, or ``None`` when the factory
      has no return annotation (autoconfigure tag rules skip those).

    A parameterized generic (``ServiceLocator[T]``) is unwrapped to its origin
    class so ``__mro__`` walks succeed.
    """
    kind = definition.kind
    provider = definition.provider
    if kind == "class":
        return cast("type", provider)
    if kind == "instance":
        return type(provider)
    try:
        key = key_type(cast("Callable[..., object]", provider), None)
    except FactoryReturnTypeIsEmptyError:
        return None
    origin = get_origin(key)
    if isinstance(origin, type):
        return origin
    return key
