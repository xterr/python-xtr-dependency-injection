"""What ``Bundle.load`` receives: a bundle's view of the services being defined.

One configurator per bundle, so every definition knows its origin. Each
operation belongs to phases: ``scan`` and ``autoconfigure`` only mean
something while bundles load — scanning and autoconfiguration run right
after — and nothing may change once the container is compiled.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Hashable, Mapping
from dataclasses import dataclass, field
from types import ModuleType
from typing import Literal

from xtr_dependency_injection.compiler._wireup_bridge import declaration_of, key_type
from xtr_dependency_injection.exception import (
    BuilderFrozenError,
    BuilderPhaseError,
    UnknownServiceError,
)

from .autoconfigurator import Apply, Autoconfigurator, Reader
from .conflict_policy import DefinitionStore
from .definition import Definition, Lifetime, Origin, ServiceKey

__all__ = [
    "BuildState",
    "DecorationRequest",
    "ResettableRequest",
    "ServiceConfigurator",
    "kind_of",
]

Phase = Literal["load", "autoconfigure", "process", "frozen"]
Kind = Literal["class", "factory", "instance", "declared"]


@dataclass(frozen=True, slots=True)
class ResettableRequest:
    """A ``resettable()`` call, resolved against the final definitions."""

    key: ServiceKey
    method: str


@dataclass(frozen=True, slots=True)
class DecorationRequest:
    """A decoration asked for by ``builder.decorate`` or ``@as_decorator``."""

    key: ServiceKey
    decorator: type | Callable[..., object]
    priority: int
    name: str
    order: int


@dataclass(slots=True)
class BuildState:
    """Everything one build's configurators and builders share.

    Attributes:
        env: The environment being built.
        debug: Whether the kernel runs in debug mode.
        bundles: Active bundle names, in dependency order.
        configs: Resolved config by bundle name.
        phase: The current phase.
        store: The definitions.
        late_scans: Resources ``scan()`` asked for, with the asking bundle.
        autoconfigurators: What ``autoconfigure()`` registered.
        parameters: Parameters bundles contributed, with their source.
        resettables: ``resettable()`` requests.
        decorations: Decoration requests.
    """

    env: str
    debug: bool
    bundles: tuple[str, ...]
    configs: Mapping[str, object]
    phase: Phase = "load"
    store: DefinitionStore = field(default_factory=DefinitionStore)
    late_scans: list[tuple[str, tuple[str | ModuleType, ...]]] = field(default_factory=list)
    autoconfigurators: list[Autoconfigurator] = field(default_factory=list)
    parameters: list[tuple[str, Mapping[str, object]]] = field(default_factory=list)
    resettables: list[ResettableRequest] = field(default_factory=list)
    decorations: list[DecorationRequest] = field(default_factory=list)


class ServiceConfigurator:
    """Defines services on behalf of one bundle.

    Attributes:
        env: The environment being built.
        debug: Whether the kernel runs in debug mode.
    """

    __slots__: tuple[str, ...] = ("_origin", "_state", "debug", "env")

    env: str
    debug: bool
    _state: BuildState
    _origin: Origin

    def __init__(self, state: BuildState, origin: Origin) -> None:
        """Define services into ``state``, as ``origin``."""
        self._state = state
        self._origin = origin
        self.env = state.env
        self.debug = state.debug

    def has_bundle(self, name: str) -> bool:
        """Return whether the bundle ``name`` is active in this build."""
        return name in self._state.bundles

    def instance(
        self,
        obj: object,
        /,
        *,
        as_type: type | None = None,
        qualifier: Hashable | None = None,
        priority: int = 0,
    ) -> None:
        """Provide ``obj`` itself, under ``as_type`` (default: its own type)."""
        self._allow("instance", "load", "autoconfigure", "process")
        key = (as_type if as_type is not None else type(obj), qualifier)
        self._add(key, obj, "instance", "singleton", priority)

    def factory(
        self,
        fn: Callable[..., object],
        /,
        *,
        lifetime: Lifetime = "singleton",
        as_type: type | None = None,
        qualifier: Hashable | None = None,
        priority: int = 0,
    ) -> None:
        """Provide what ``fn`` returns — or yields, cleaned up after — under its return type.

        Raises:
            TypeError: If ``fn`` is not a plain function.
            FactoryReturnTypeIsEmptyError: If ``fn`` has no return
                annotation.
        """
        self._allow("factory", "load", "autoconfigure", "process")
        if not inspect.isfunction(fn):
            msg = f"factory() takes a function, not {fn!r}"
            raise TypeError(msg)
        self._add((key_type(fn, as_type), qualifier), fn, "factory", lifetime, priority)

    def service(
        self,
        cls: type,
        /,
        *,
        lifetime: Lifetime = "singleton",
        as_type: type | None = None,
        qualifier: Hashable | None = None,
        priority: int = 0,
    ) -> None:
        """Provide ``cls``, built by the container from its constructor.

        Does nothing when a definition for ``cls`` itself already exists — as
        when the application marked it ``@injectable`` and a bundle's
        autoconfiguration registers it again.
        """
        self._allow("service", "load", "autoconfigure", "process")
        if self._state.store.has_provider(cls):
            return
        key = (as_type if as_type is not None else cls, qualifier)
        self._add(key, cls, "class", lifetime, priority)

    def scan(self, *resources: str | ModuleType) -> None:
        """Scan ``resources`` too, once every bundle has loaded, as this bundle's.

        This is how a bundle scans a module only when a peer is active.
        """
        self._allow("scan", "load")
        self._state.late_scans.append((self._origin.name, resources))

    def autoconfigure(self, reader: Reader, apply: Apply) -> None:
        """Call ``apply`` for every metadata item ``reader`` finds on a scanned candidate."""
        self._allow("autoconfigure", "load")
        self._state.autoconfigurators.append(Autoconfigurator(self._origin.name, reader, apply))

    def parameters(self, values: Mapping[str, object], /) -> None:
        """Merge ``values`` into the parameters, read with ``Inject(config=...)``."""
        self._allow("parameters", "load", "autoconfigure", "process")
        self._state.parameters.append((str(self._origin), values))

    def resettable(
        self, as_type: type, /, *, qualifier: Hashable | None = None, method: str = "reset"
    ) -> None:
        """Have ``ServicesResetter`` call ``method`` on the service, once it is built.

        Resolved after every definition is final, so the order relative to
        the service's own definition does not matter.
        """
        self._allow("resettable", "load", "autoconfigure", "process")
        self._state.resettables.append(ResettableRequest((as_type, qualifier), method))

    def _add(
        self, key: ServiceKey, provider: object, kind: Kind, lifetime: Lifetime, priority: int
    ) -> None:
        definition = Definition(key, provider, kind, lifetime, self._origin, priority)
        self._state.store.add(definition)

    def _allow(self, operation: str, *phases: Phase) -> None:
        phase = self._state.phase
        if phase == "frozen":
            raise BuilderFrozenError(operation)
        if phase not in phases:
            raise BuilderPhaseError(operation, phase)

    def _require(self, key: ServiceKey, operation: str) -> Definition:
        definition = self._state.store.get(key)
        if definition is None:
            raise UnknownServiceError(key, operation)
        return definition


def kind_of(provider: object) -> Kind:
    """Return how ``provider`` is registered, judged from what it is."""
    if declaration_of(provider) is not None:
        return "declared"
    if isinstance(provider, type):
        return "class"
    if inspect.isfunction(provider):
        return "factory"
    return "instance"
