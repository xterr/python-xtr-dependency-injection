"""The kernel's :class:`ContainerInterface` implementation over a wireup ``AsyncContainer``.

Bundles receive one of these as ``self.container`` before their ``boot`` runs.
It is the only place a wireup container is wrapped for the public
``ContainerInterface`` seam; the engine stays out of every consumer's sight.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast, final, override

from wireup.errors import UnknownParameterError
from xtr_service_contracts import ContainerInterface

from xtr_dependency_injection._text import safe_str
from xtr_dependency_injection.compiler._wireup_bridge import is_registered, parameters_of
from xtr_dependency_injection.config.env_placeholder import (
    ENV_PARAMETERS_ROOT,
    env_placeholders_in,
    resolve_env_placeholders,
)
from xtr_dependency_injection.exception import (
    EnvPlaceholderError,
    KernelShutDownError,
    ParameterNotFoundError,
    ServiceNotFoundError,
    ServiceResolutionError,
    UnitOfWorkClosedError,
)

from ._unit_scope import is_shut_down
from .env_var_processors_locator import EnvVarProcessorsLocator

if TYPE_CHECKING:
    from collections.abc import Hashable

    from wireup import AsyncContainer, ScopedAsyncContainer

    from ._unit_scope import Unit

__all__ = ["WireupContainer"]


_SCOPE_ADVICE = (
    "scoped and transient services are built inside a scope; resolve them from an "
    "injected callable, from bind_callable(container, target, per_call_scope=True), "
    "or from the container unit_of_work(container) gives"
)
"""How this package resolves a scoped or transient service, for the get() advice."""


@final
class WireupContainer(ContainerInterface):
    """Wraps a wireup ``AsyncContainer`` behind :class:`ContainerInterface`.

    Given a unit of work of that container too, it is the unit's view: it
    resolves scoped services — once each, for the unit's lifetime — as well
    as singletons, and reads the same parameters. Once the unit has exited
    it resolves nothing, so a task that outlived the unit cannot reach the
    services it released.
    """

    __slots__ = ("_container", "_unit")

    def __init__(self, container: AsyncContainer, unit: Unit | None = None) -> None:
        """Wrap ``container``, resolving through ``unit``'s scope when one is given."""
        self._container = container
        self._unit = unit

    @override
    async def get[T](self, service: type[T], /, qualifier: Hashable | None = None) -> T:
        """Return the service registered under ``service`` and ``qualifier``.

        Raises:
            KernelShutDownError: If the kernel this container belongs to has
                shut down.
            UnitOfWorkClosedError: If this is the view of a unit of work that
                has exited.
            ServiceNotFoundError: If nothing is registered under the key.
            ServiceResolutionError: If building the service failed.
        """
        resolver: AsyncContainer | ScopedAsyncContainer = self._container
        if is_shut_down(self._container):
            raise KernelShutDownError
        if self._unit is not None:
            scope = self._unit.scope
            if scope is None:
                raise UnitOfWorkClosedError
            resolver = scope
        if not is_registered(self._container, service, qualifier):
            raise ServiceNotFoundError((service, qualifier))
        try:
            return await resolver.get(service, qualifier)
        except ServiceNotFoundError:
            raise
        except Exception as error:
            reason = safe_str(error)
            advice = _SCOPE_ADVICE if "scope mismatch" in reason.lower() else None
            raise ServiceResolutionError((service, qualifier), reason, advice=advice) from error

    @override
    def has(self, service: type[object], /, qualifier: Hashable | None = None) -> bool:
        return is_registered(self._container, service, qualifier)

    @override
    def get_parameter(self, name: str, /) -> object:
        """Return the parameter ``name``.

        Raises:
            ParameterNotFoundError: If no such parameter exists.
            EnvPlaceholderError: If the parameter holds an environment
                placeholder: it is resolved when injected, or through
                :meth:`resolve_env_placeholders`, never read raw.
        """
        try:
            value = cast("object", self._container.config.get(name))
        except UnknownParameterError as error:
            raise ParameterNotFoundError(name) from error
        held = env_placeholders_in(value)
        if held:
            reason = (
                f"parameter {name!r} holds it; inject the parameter, or await "
                "resolve_env_placeholders(container.get_parameter_raw(name))"
            )
            raise EnvPlaceholderError(held[0].expression, reason)
        return value

    def get_parameter_raw(self, name: str, /) -> object:
        """Return the parameter ``name`` as stored, environment placeholders included.

        Raises:
            ParameterNotFoundError: If no such parameter exists.
        """
        try:
            return cast("object", self._container.config.get(name))
        except UnknownParameterError as error:
            raise ParameterNotFoundError(name) from error

    def get_parameters(self) -> dict[str, object]:
        """Return every parameter, nested, as stored — environment placeholders included."""
        return {
            name: value
            for name, value in parameters_of(self._container).items()
            if name != ENV_PARAMETERS_ROOT
        }

    async def get_env(self, name: str, /) -> object:
        """Return the value of the environment variable expression ``name`` (``"int:PORT"``).

        Raises:
            EnvPlaceholderError: If a prefix names no processor.
            MissingEnvironmentVariableError: If a variable is not set.
            InvalidEnvironmentVariableError: If a processor refuses a value.
        """
        processors = await self.get(EnvVarProcessorsLocator)
        return processors.get_env(name)

    async def resolve_env_placeholders[T](self, value: T, /) -> T:
        """Return ``value`` with every environment placeholder it holds resolved.

        Only what holds a placeholder is rebuilt; a value without one is
        returned as is, and no processor is built for it.
        """
        if not env_placeholders_in(value):
            return value
        processors = await self.get(EnvVarProcessorsLocator)
        return cast("T", resolve_env_placeholders(value, processors.get_env))

    @override
    def has_parameter(self, name: str, /) -> bool:
        try:
            _ = cast("object", self._container.config.get(name))
        except UnknownParameterError:
            return False
        return True

    def _engine(self) -> AsyncContainer:  # pyright: ignore[reportUnusedFunction] — called cross-module via SLF001.
        """Return the wrapped engine container — for kernel-internal use only.

        Public consumers see this container behind :class:`ContainerInterface`;
        the kernel's internal glue (``bind_callable``, ``call_injected``,
        ``testing.boot_for_test``) needs the raw engine to enter scopes, run
        overrides and inject callables. A unit of work's view returns the
        root engine too, never its scope.
        """
        return self._container
