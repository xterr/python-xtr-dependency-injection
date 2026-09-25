"""What ``Bundle.process`` and ``@compiler_pass`` receive: every definition, still mutable.

By now every bundle has loaded and autoconfiguration has run, so a pass sees
the whole container — what exists, which config each bundle resolved — and
may still add, replace, remove or decorate.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar, cast, final, overload

from xtr_dependency_injection.exception import MissingBundleError, UnknownConfigTypeError

from .definition import Definition, Lifetime
from .service_configurator import DecorationRequest, Kind, ServiceConfigurator, kind_of

if TYPE_CHECKING:
    from collections.abc import Callable, Hashable

__all__ = ["ContainerBuilder"]

C = TypeVar("C")


@final
class ContainerBuilder(ServiceConfigurator):
    """A whole-container view for processing, on behalf of one bundle or compiler pass.

    ``scan`` and ``autoconfigure`` are refused here: both have already run.
    """

    def has(self, as_type: type, /, qualifier: Hashable | None = None) -> bool:
        """Return whether a service is defined for ``(as_type, qualifier)``."""
        return self._state.store.get((as_type, qualifier)) is not None

    def definitions(self, as_type: type | None = None, /) -> tuple[Definition, ...]:
        """Return every definition, or those provided under ``as_type``, in declaration order."""
        every = self._state.store.definitions()
        return every if as_type is None else tuple(d for d in every if d.key[0] is as_type)

    @overload
    def config_of(self, bundle: str, /) -> object: ...
    @overload
    def config_of(self, bundle: type[C], /) -> C: ...
    def config_of(self, bundle: str | type[C], /) -> object:
        """Return the resolved config of a bundle, by name or by config type.

        Raises:
            MissingBundleError: If no active bundle has that name.
            UnknownConfigTypeError: If no active bundle has that config type.
        """
        configs = self._state.configs
        if isinstance(bundle, str):
            if bundle not in configs:
                raise MissingBundleError(bundle, str(self._origin), "it is not active")
            return configs[bundle]
        for value in configs.values():
            if type(value) is bundle:
                return cast("C", value)
        raise UnknownConfigTypeError(f"config_of by {self._origin}", bundle, None)

    def replace(
        self,
        as_type: type,
        provider: object,
        /,
        *,
        qualifier: Hashable | None = None,
        kind: Kind | None = None,
        lifetime: Lifetime | None = None,
    ) -> None:
        """Replace the service ``(as_type, qualifier)`` with ``provider``, on purpose.

        The kind is inferred from ``provider`` unless given; the lifetime, and
        the position in collections, stay the replaced definition's.

        Raises:
            UnknownServiceError: If no such service is defined.
        """
        self._allow("replace", "process")
        existing = self._require((as_type, qualifier), "replace")
        self._state.store.replace(
            Definition(
                key=existing.key,
                provider=provider,
                kind=kind if kind is not None else kind_of(provider),
                lifetime=lifetime if lifetime is not None else existing.lifetime,
                origin=self._origin,
                priority=existing.priority,
                reset_method=existing.reset_method,
            )
        )

    def remove(self, as_type: type, /, *, qualifier: Hashable | None = None) -> None:
        """Remove the service ``(as_type, qualifier)``.

        Raises:
            UnknownServiceError: If no such service is defined.
        """
        self._allow("remove", "process")
        definition = self._require((as_type, qualifier), "remove")
        self._state.store.remove(definition.key)

    def decorate(
        self,
        as_type: type,
        decorator: type | Callable[..., object],
        /,
        *,
        qualifier: Hashable | None = None,
        priority: int = 0,
    ) -> None:
        """Decorate the service ``(as_type, qualifier)`` with ``decorator``.

        The decorator takes the service's place, and receives it through its
        one ``Inner[as_type]`` parameter.

        Raises:
            UnknownServiceError: If no such service is defined.
        """
        self._allow("decorate", "process")
        key = self._require((as_type, qualifier), "decorate").key
        name = f"{getattr(decorator, '__module__', '?')}:{getattr(decorator, '__qualname__', '?')}"
        order = len(self._state.decorations)
        self._state.decorations.append(DecorationRequest(key, decorator, priority, name, order))
