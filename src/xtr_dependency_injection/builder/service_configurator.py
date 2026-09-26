"""What ``Bundle.load_extension`` receives: a bundle's view of the services being defined.

One configurator per bundle, so every definition knows its origin. Nothing
may change once the container is compiled.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Hashable, Mapping
from dataclasses import dataclass, field
from types import ModuleType
from typing import TYPE_CHECKING, Literal

from xtr_dependency_injection.compiler._wireup_bridge import key_type
from xtr_dependency_injection.compiler.compiler import Compiler
from xtr_dependency_injection.exception import BuilderFrozenError, BuilderPhaseError
from xtr_dependency_injection.parameter_bag.env_placeholder_parameter_bag import (
    EnvPlaceholderParameterBag,
)

from .autoconfigurator import Autoconfigurator
from .autoconfigure_rule import AutoconfigureRule
from .conflict_policy import DefinitionStore, record_alias
from .definition import Definition, Lifetime, Origin, ServiceKey

if TYPE_CHECKING:
    # String annotations kept by `from __future__ import annotations`; read only
    # by type checkers on the dataclass fields below.
    from xtr_dependency_injection.compiler.wireup_compiler import (
        Decoration,  # noqa: TC004 — see above.
    )
    from xtr_dependency_injection.scan.scanned_object import (
        ScannedObject,  # noqa: TC004 — see above.
    )

__all__ = [
    "BuildState",
    "Prepend",
    "ServiceConfigurator",
]


Phase = Literal["build", "prepend", "load", "process", "frozen"]
Kind = Literal["class", "factory", "instance"]


@dataclass(frozen=True, slots=True)
class Prepend:
    """One recorded ``prepend_extension_config`` call, to apply while resolving configs.

    Attributes:
        source: The bundle whose ``prepend_extension`` requested it.
        target: The name or the config type of the bundle being prepended.
        fn: The transform to apply.
        description: A human-readable name for the transform.
    """

    source: str
    target: str | type
    fn: Callable[[object], object]
    description: str


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
        late_scans: Resources ``load()`` asked for, with the asking bundle.
        autoconfigurators: What ``builder.register_attribute_for_autoconfiguration``
            registered.
        autoconfigure_rules: What ``builder.register_for_autoconfiguration``
            registered — nominal subclass rules — then the rules
            ``RegisterAutoconfigureAttributesPass`` reads off scanned
            classes; applied by ``ResolveInstanceofConditionalsPass`` to
            every non-kernel definition whose built type has the rule's type
            in its ``__mro__``.
        parameters: Every parameter source — the kernel's, each bundle's, each
            ``@parameters`` function's — with its origin, merged at compile
            time with conflicts refused.
        parameter_bag: The same parameters, merged, for reading and
            resolving ``%name%`` references while the kernel builds.
        prepends: Config prepends bundles recorded, in call order.
        aliases: The alias table ``alias_key -> target_key``.
        alias_origins: Who contributed each alias, for the conflict policy.
        compiler: The compiler: its pass config holds every pass to run,
            and its log what the passes reported.
        candidates: Every service candidate the scans found, which the
            autoconfiguration passes look at.
        scanned_decorators: Every scanned ``@as_decorator`` class or factory.
        environ: Where the environment variable processors read variables;
            ``None`` reads the live process environment.
        decorations: Per key, the decorations to apply — populated by the
            built-in ``OPTIMIZE`` pass and read by the wireup emitter.
    """

    env: str
    debug: bool
    bundles: tuple[str, ...]
    configs: Mapping[str, object]
    phase: Phase = "load"
    store: DefinitionStore = field(default_factory=DefinitionStore)
    late_scans: list[tuple[str, tuple[str | ModuleType, ...]]] = field(default_factory=list)
    autoconfigurators: list[Autoconfigurator] = field(default_factory=list)
    autoconfigure_rules: list[AutoconfigureRule] = field(default_factory=list)
    parameters: list[tuple[Origin, Mapping[str, object]]] = field(default_factory=list)
    parameter_bag: EnvPlaceholderParameterBag = field(default_factory=EnvPlaceholderParameterBag)
    prepends: list[Prepend] = field(default_factory=list)
    aliases: dict[ServiceKey, ServiceKey] = field(default_factory=dict)
    alias_origins: dict[ServiceKey, Origin] = field(default_factory=dict)
    compiler: Compiler = field(default_factory=Compiler)
    candidates: list[ScannedObject] = field(default_factory=list)
    scanned_decorators: list[ScannedObject] = field(default_factory=list)
    environ: Mapping[str, str] | None = None

    def add_parameters(self, origin: Origin, values: Mapping[str, object]) -> None:
        """Record ``values`` as a parameter source of ``origin``, and merge them into the bag."""
        self.parameters.append((origin, values))
        self.parameter_bag.add(values)

    decorations: dict[ServiceKey, list[Decoration]] = field(default_factory=dict)


class ServiceConfigurator:
    """Defines services on behalf of one bundle.

    ``set``, ``instance``, ``alias`` and ``load`` cover every way a bundle
    contributes a service from ``load_extension``.
    """

    __slots__: tuple[str, ...] = ("_origin", "_state")

    _state: BuildState
    _origin: Origin

    def __init__(self, state: BuildState, origin: Origin) -> None:
        """Define services into ``state``, as ``origin``."""
        self._state = state
        self._origin = origin

    def instance(
        self,
        obj: object,
        /,
        *,
        qualifier: Hashable | None = None,
    ) -> Definition:
        """Provide ``obj`` itself, under its own type.

        The key is always ``(type(obj), qualifier)``. Register an alias to
        expose it under an interface (:meth:`alias`).
        """
        self._allow("instance", "load", "process")
        key: ServiceKey = (type(obj), qualifier)
        definition = Definition(key, obj, "instance", "singleton", self._origin)
        self._state.store.add(definition)
        return definition

    def set(
        self,
        target: type | Callable[..., object],
        /,
        *,
        qualifier: Hashable | None = None,
        lifetime: Lifetime = "singleton",
    ) -> Definition:
        """Register ``target`` — a class or a factory function — as a service.

        A class is registered under its own type; a function under its
        evaluated return type. Same key + same provider is a no-op.

        Raises:
            TypeError: If ``target`` is not a class or a plain function.
        """
        self._allow("set", "load", "process")
        if isinstance(target, type):
            key: ServiceKey = (target, qualifier)
            kind: Kind = "class"
        elif inspect.isfunction(target):
            key = (key_type(target), qualifier)
            kind = "factory"
        else:
            msg = f"set() takes a class or a function, not {target!r}"
            raise TypeError(msg)
        existing = self._state.store.get(key)
        if existing is not None and existing.provider is target:
            return existing
        definition = Definition(key, target, kind, lifetime, self._origin)
        self._state.store.add(definition)
        return definition

    def alias(
        self,
        alias: type,
        target: type,
        /,
        *,
        alias_qualifier: Hashable | None = None,
        target_qualifier: Hashable | None = None,
    ) -> None:
        """Register an alias from ``(alias, alias_qualifier)`` to ``(target, target_qualifier)``.

        The alias target is validated at compile time (missing →
        ``UnknownServiceError``).
        """
        self._allow("alias", "load", "process")
        record_alias(
            self._state.aliases,
            self._state.alias_origins,
            (alias, alias_qualifier),
            (target, target_qualifier),
            self._origin,
        )

    def load(self, *resources: str | ModuleType) -> None:
        """Scan ``resources`` too, once every bundle has loaded, as this bundle's.

        This is how a bundle scans a module only when a peer is active.
        """
        self._allow("load", "load")
        self._state.late_scans.append((self._origin.name, resources))

    def _allow(self, operation: str, *phases: Phase) -> None:
        phase = self._state.phase
        if phase == "frozen":
            raise BuilderFrozenError(operation)
        if phase not in phases:
            raise BuilderPhaseError(operation, phase)
