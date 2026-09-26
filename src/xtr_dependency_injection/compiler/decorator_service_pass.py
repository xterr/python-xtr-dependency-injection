"""The built-in ``OPTIMIZE`` pass: turn decoration requests into decorations.

Every ``Definition.decorates`` and every scanned ``@as_decorator`` marker
becomes an entry in ``state.decorations``, sorted so the highest priority
wraps the original first, with each decorator removed from its own key.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from xtr_dependency_injection.builder.definition import Definition, Origin, ServiceKey
from xtr_dependency_injection.compiler.priority_tagged_service import by_priority
from xtr_dependency_injection.compiler.registration import _null_decorator_factory
from xtr_dependency_injection.compiler.wireup_compiler import Decoration
from xtr_dependency_injection.decorator.as_decorator import (
    DecoratedParameter,
    OnInvalid,
    decorated_parameter_of,
    decorator_of,
)
from xtr_dependency_injection.exception import DecoratorSignatureError, UnknownServiceError
from xtr_dependency_injection.exception._naming import qualified_name

if TYPE_CHECKING:
    from collections.abc import Sequence

    from xtr_dependency_injection.builder.container_builder import ContainerBuilder
    from xtr_dependency_injection.builder.service_configurator import BuildState
    from xtr_dependency_injection.scan.scanned_object import ScannedObject

__all__ = ["resolve_decorations_pass"]


def resolve_decorations_pass(
    builder: ContainerBuilder, scanned_decorators: Sequence[ScannedObject]
) -> None:
    """OPTIMIZE built-in: build ``state.decorations`` from decoration requests.

    Reads every ``Definition.decorates`` set through ``set_decorated_service``
    and every scanned ``@as_decorator`` marker, sorts them by priority
    (highest wraps the original first), populates ``state.decorations`` and
    removes each decorator definition from its own key so the decorator lives
    only under the target's key (the decorator replaces the target under
    that key).

    ``on_invalid`` chooses what happens when the target is not defined:

    - :attr:`OnInvalid.EXCEPTION` raises :class:`UnknownServiceError`;
    - :attr:`OnInvalid.IGNORE` drops the decorator silently;
    - :attr:`OnInvalid.NULL` keeps the decorator under the target key and
      injects ``None`` for its ``AutowireDecorated`` parameter (the
      annotation must be ``T | None``).

    Raises:
        UnknownServiceError: :attr:`OnInvalid.EXCEPTION` and target missing.
        DecoratorSignatureError: The decorator has none, several, or one
            ``Annotated[..., AutowireDecorated()]`` parameter of the wrong
            type - or :attr:`OnInvalid.NULL` on a parameter that does not
            allow ``None``.
    """
    state = builder._state  # noqa: SLF001  # pyright: ignore[reportPrivateUsage] — the built-in pass reads state directly.
    requests = _collect_pending_decorations(state, scanned_decorators)
    for request in by_priority(requests, priority=lambda r: r.priority, order=lambda r: r.order):
        target = state.store.get(request.key)
        if target is None and request.on_invalid is OnInvalid.EXCEPTION:
            raise UnknownServiceError(request.key, "decorate")
        if target is None and request.on_invalid is OnInvalid.IGNORE:
            _remove_own_key(state, request.own_key)
            continue
        parameter = decorated_parameter_of(request.decorator, request.key[0])
        _remove_own_key(state, request.own_key)
        if target is None:
            _register_null_decorator(state, request, parameter)
            continue
        state.decorations.setdefault(request.key, []).append(
            Decoration(request.decorator, parameter.name, request.name)
        )


def _collect_pending_decorations(
    state: BuildState, scanned_decorators: Sequence[ScannedObject]
) -> list[_PendingDecoration]:
    """Gather decorations from ``set_decorated_service`` and scanned ``@as_decorator``."""
    requests: list[_PendingDecoration] = []
    order = 0
    for definition in state.store.entries():
        if definition.decorates is None:
            continue
        requests.append(
            _PendingDecoration(
                key=definition.decorates.key,
                decorator=cast("type | Callable[..., object]", definition.provider),
                priority=definition.decorates.priority,
                on_invalid=definition.decorates.on_invalid,
                name=qualified_name(definition.provider),
                order=order,
                own_key=definition.key,
                origin=definition.origin,
            )
        )
        order += 1
    for scanned in scanned_decorators:
        marker = decorator_of(scanned.obj)
        if marker is None:
            continue
        origin = (
            Origin("app", scanned.name)
            if scanned.owner is None
            else Origin("bundle", scanned.owner, f"compiler pass {scanned.name}")
        )
        requests.append(
            _PendingDecoration(
                key=(marker.target, marker.qualifier),
                decorator=cast("type | Callable[..., object]", scanned.obj),
                priority=marker.priority,
                on_invalid=marker.on_invalid,
                name=scanned.name,
                order=order,
                own_key=None,
                origin=origin,
            )
        )
        order += 1
    return requests


def _remove_own_key(state: BuildState, own_key: ServiceKey | None) -> None:
    """Drop the decorator's own-key definition so it lives only under the target key."""
    if own_key is None:
        return
    if state.store.get(own_key) is not None:
        state.store.remove(own_key)


def _register_null_decorator(
    state: BuildState, request: _PendingDecoration, parameter: DecoratedParameter
) -> None:
    """Register a decorator under a missing target with ``None`` for its inner parameter."""
    if not parameter.allows_none:
        raise DecoratorSignatureError(
            request.name,
            (
                "on_invalid=OnInvalid.NULL requires the AutowireDecorated parameter "
                f"{parameter.name!r} to allow None (annotate it as T | None)"
            ),
        )
    target_type, _ = request.key
    factory = _null_decorator_factory(request.decorator, parameter.name, target_type)
    state.store.add(
        Definition(
            key=request.key,
            provider=factory,
            kind="factory",
            lifetime="singleton",
            origin=Origin(
                request.origin.kind,
                request.origin.name,
                f"decorator of missing {qualified_name(target_type)}",
            ),
        )
    )


@dataclass(frozen=True, slots=True)
class _PendingDecoration:
    """Internal record of one decoration to apply, gathered by :func:`resolve_decorations_pass`."""

    key: ServiceKey
    decorator: type | Callable[..., object]
    priority: int
    on_invalid: OnInvalid
    name: str
    order: int
    own_key: ServiceKey | None
    origin: Origin
