"""What bundle hooks and ``@compiler_pass`` receive: a view of the container being built.

By now every bundle has loaded and autoconfiguration has run, so a pass sees
the whole container — what exists, which config each bundle resolved — and
may still add, remove or mutate definitions. Earlier phases (``build``,
``prepend_extension``, ``load_extension``) also receive one, but with
narrower operations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar, cast, final, overload

from xtr_dependency_injection.compiler.pass_stage import PassStage
from xtr_dependency_injection.exception import (
    ConfigProviderError,
    MissingBundleError,
    UnknownConfigTypeError,
    UnknownServiceError,
)
from xtr_dependency_injection.exception._naming import qualified_name

from .autoconfigurator import Apply, Autoconfigurator, Reader
from .autoconfigure_rule import AutoconfigureRule
from .conflict_policy import record_alias
from .definition import Definition, Lifetime, Origin, ServiceKey
from .service_configurator import BuildState, Phase, Prepend

if TYPE_CHECKING:
    from collections.abc import Callable, Hashable

    from xtr_dependency_injection.compiler.compiler import Compiler
    from xtr_dependency_injection.compiler.compiler_pass_interface import CompilerPassInterface
    from xtr_dependency_injection.parameter_bag.env_placeholder_parameter_bag import (
        EnvPlaceholderParameterBag,
    )

__all__ = ["ContainerBuilder"]

C = TypeVar("C")


@final
class ContainerBuilder:
    """A whole-container view for a bundle or a compiler pass.

    In phase ``build``, only parameter reads/writes, container queries,
    :meth:`register_for_autoconfiguration` and :meth:`register_attribute_for_autoconfiguration`
    are allowed. In phase ``prepend``, additionally
    :meth:`prepend_extension_config`. In phase ``load`` and ``process``,
    definition/alias/tag mutations too. See the module docstring for the
    full phase → allowed-operations table.
    """

    __slots__: tuple[str, ...] = ("_origin", "_state")

    _state: BuildState
    _origin: Origin

    def __init__(self, state: BuildState, origin: Origin) -> None:
        """Bind this builder to ``state`` as ``origin``."""
        self._state = state
        self._origin = origin

    def has(self, service: type, /, qualifier: Hashable | None = None) -> bool:
        """Return whether a definition or alias exists for ``(service, qualifier)``."""
        key = (service, qualifier)
        return self._state.store.get(key) is not None or key in self._state.aliases

    def register(
        self,
        service: type,
        /,
        *,
        qualifier: Hashable | None = None,
        lifetime: Lifetime = "singleton",
    ) -> Definition:
        """Register ``service`` as a class definition and return it, for further mutation.

        Allowed in phases ``load`` and ``process``.
        """
        self._allow("register", "load", "process")
        key: ServiceKey = (service, qualifier)
        definition = Definition(key, service, "class", lifetime, self._origin)
        self._state.store.add(definition)
        return definition

    def set_definition(self, definition: Definition, /) -> Definition:
        """Overwrite the definition of ``definition.key`` with ``definition``.

        Allowed in phases ``load`` and ``process``. Records the previous
        origin as an override.
        """
        self._allow("set_definition", "load", "process")
        existing = self._state.store.get(definition.key)
        if existing is None:
            self._state.store.add(definition)
        else:
            self._state.store.overwrite(definition)
        return definition

    def get_definition(self, service: type, /, qualifier: Hashable | None = None) -> Definition:
        """Return the definition of ``(service, qualifier)``.

        Raises:
            UnknownServiceError: If no such definition exists.
        """
        return self._require((service, qualifier), "get_definition")

    def has_definition(self, service: type, /, qualifier: Hashable | None = None) -> bool:
        """Return whether the definition of ``(service, qualifier)`` exists.

        Unlike :meth:`has`, this does not follow aliases.
        """
        return self._state.store.get((service, qualifier)) is not None

    def find_definition(self, service: type, /, qualifier: Hashable | None = None) -> Definition:
        """Return the definition ``(service, qualifier)`` resolves to, following aliases.

        Raises:
            UnknownServiceError: If neither a definition nor an alias
                resolves to a definition.
        """
        key: ServiceKey = (service, qualifier)
        seen: set[ServiceKey] = set()
        while key in self._state.aliases and key not in seen:
            seen.add(key)
            key = self._state.aliases[key]
        return self._require(key, "find_definition")

    def remove_definition(self, service: type, /, qualifier: Hashable | None = None) -> None:
        """Remove the definition of ``(service, qualifier)``.

        Raises:
            UnknownServiceError: If no such definition exists.
        """
        self._allow("remove_definition", "load", "process")
        definition = self._require((service, qualifier), "remove_definition")
        self._state.store.remove(definition.key)

    def get_definitions(self) -> tuple[Definition, ...]:
        """Return every definition, in declaration order."""
        return self._state.store.entries()

    def set_alias(
        self,
        alias: type,
        target: type,
        /,
        *,
        alias_qualifier: Hashable | None = None,
        target_qualifier: Hashable | None = None,
    ) -> None:
        """Register an alias from ``(alias, alias_qualifier)`` to ``(target, target_qualifier)``.

        Allowed in phases ``load`` and ``process``.
        """
        self._allow("set_alias", "load", "process")
        record_alias(
            self._state.aliases,
            self._state.alias_origins,
            (alias, alias_qualifier),
            (target, target_qualifier),
            self._origin,
        )

    def get_aliases(self) -> dict[ServiceKey, ServiceKey]:
        """Return every alias, ``alias_key -> target_key``, in declaration order."""
        return dict(self._state.aliases)

    def get_alias(self, alias: type, /, qualifier: Hashable | None = None) -> ServiceKey:
        """Return the target key for ``(alias, qualifier)``.

        Raises:
            UnknownServiceError: If no such alias exists.
        """
        key: ServiceKey = (alias, qualifier)
        target = self._state.aliases.get(key)
        if target is None:
            raise UnknownServiceError(key, "get_alias")
        return target

    def has_alias(self, alias: type, /, qualifier: Hashable | None = None) -> bool:
        """Return whether ``(alias, qualifier)`` is aliased to another key."""
        return (alias, qualifier) in self._state.aliases

    def remove_alias(self, alias: type, /, qualifier: Hashable | None = None) -> None:
        """Remove the alias ``(alias, qualifier)``.

        Raises:
            UnknownServiceError: If no such alias exists.
        """
        self._allow("remove_alias", "load", "process")
        key: ServiceKey = (alias, qualifier)
        if key not in self._state.aliases:
            raise UnknownServiceError(key, "remove_alias")
        del self._state.aliases[key]
        _ = self._state.alias_origins.pop(key, None)

    def find_tagged_service_ids(self, tag: str, /) -> dict[ServiceKey, list[dict[str, object]]]:
        """Return every definition tagged ``tag``, mapped to its attribute list.

        Definition order.
        """
        return {
            definition.key: definition.get_tag(tag)
            for definition in self._state.store.entries()
            if definition.has_tag(tag)
        }

    def add_compiler_pass(
        self,
        compiler_pass: CompilerPassInterface,
        /,
        *,
        stage: PassStage = PassStage.BEFORE_OPTIMIZATION,
        priority: int = 0,
    ) -> None:
        """Register ``compiler_pass`` to run in ``stage`` at ``priority``.

        Only allowed in phase ``build`` (from :meth:`Bundle.build`). The pass
        runs with a builder bound to this builder's origin.

        Raises:
            TypeError: If ``compiler_pass`` does not implement
                :class:`CompilerPassInterface`.
        """
        self._allow("add_compiler_pass", "build")
        self._state.compiler.add_pass(compiler_pass, stage, priority, origin=self._origin)

    def get_compiler(self) -> Compiler:
        """Return the compiler: its pass config and its log."""
        return self._state.compiler

    def log(self, compiler_pass: CompilerPassInterface, message: str, /) -> None:
        """Record ``message`` in the compiler log, under ``compiler_pass``."""
        self._state.compiler.log(compiler_pass, message)

    def register_for_autoconfiguration(self, type_: type, /) -> AutoconfigureRule:
        """Return an :class:`AutoconfigureRule` for every subclass of ``type_``.

        Allowed in phases ``build`` and ``load``.
        ``ResolveInstanceofConditionalsPass`` applies each rule to every
        non-kernel definition whose built
        type has ``type_`` in its ``__mro__`` (a nominal subclass check). A
        tag already carried on a definition wins over the rule's — explicit
        stays.
        """
        self._allow("register_for_autoconfiguration", "build", "load")
        rule = AutoconfigureRule(type_=type_)
        self._state.autoconfigure_rules.append(rule)
        return rule

    def register_attribute_for_autoconfiguration(self, reader: Reader, callback: Apply, /) -> None:
        """Register a callback called for every metadata item ``reader`` finds on a candidate.

        ``AttributeAutoconfigurationPass`` runs the callback with the
        registering bundle's :class:`ServiceConfigurator`.
        """
        self._allow(
            "register_attribute_for_autoconfiguration", "build", "prepend", "load", "process"
        )
        self._state.autoconfigurators.append(Autoconfigurator(self._origin.name, reader, callback))

    def set_parameter(self, name: str, value: object, /) -> None:
        """Set the parameter ``name`` to ``value``.

        Merges into the parameter sources under this builder's origin; a
        leaf set twice by non-``app`` sources with a different value raises
        :class:`ParameterConflictError` at parameter-merge time.
        """
        self._allow("set_parameter", "build", "prepend", "load", "process")
        parts = name.split(".")
        nested: dict[str, object] = {parts[-1]: value}
        for part in reversed(parts[:-1]):
            nested = {part: nested}
        self._state.add_parameters(self._origin, nested)

    @overload
    def get_extension_config(self, bundle: str, /) -> object: ...
    @overload
    def get_extension_config(self, bundle: type[C], /) -> C: ...
    def get_extension_config(self, bundle: str | type[C], /) -> object:
        """Return the resolved config of a bundle, by name or by config type.

        Raises:
            MissingBundleError: If no active bundle has that name.
            UnknownConfigTypeError: If no active bundle has that config type.
        """
        self._allow("get_extension_config", "load", "process")
        configs = self._state.configs
        if isinstance(bundle, str):
            if bundle not in configs:
                raise MissingBundleError(bundle, str(self._origin), "it is not active")
            return configs[bundle]
        for value in configs.values():
            if type(value) is bundle:
                return cast("C", value)
        raise UnknownConfigTypeError(f"get_extension_config by {self._origin}", bundle, None)

    def prepend_extension_config(
        self, bundle: str | type[C], transform: Callable[[C], C], /
    ) -> None:
        """Adjust another bundle's config, before it is loaded.

        Only allowed in phase ``prepend`` (from :meth:`Bundle.prepend_extension`).

        Raises:
            ConfigProviderError: If ``bundle`` is a type owned by no known
                bundle, or if the target takes no config.
        """
        # Local import breaks a circular dependency with the bundle module.
        from xtr_dependency_injection.bundle import NoConfig  # noqa: PLC0415

        self._allow("prepend_extension_config", "prepend")
        described = qualified_name(transform)
        source = self._origin.name
        if isinstance(bundle, str):
            configs = self._state.configs
            if bundle in configs and type(configs[bundle]) is NoConfig:
                raise ConfigProviderError(
                    f"prepend by bundle {source}", f"bundle {bundle!r} takes no config"
                )
        self._state.prepends.append(
            Prepend(
                source=source,
                target=bundle,
                fn=cast("Callable[[object], object]", transform),
                description=described,
            )
        )

    def get_parameter(self, name: str, /) -> object:
        """Return the build-time parameter ``name`` (dotted path).

        Allowed from phase ``build`` onward.

        Raises:
            ParameterNotFoundError: If the parameter is not set.
        """
        self._allow("get_parameter", "build", "prepend", "load", "process")
        return self._state.parameter_bag.get(name)

    def has_parameter(self, name: str, /) -> bool:
        """Return whether the parameter ``name`` is defined.

        Allowed from phase ``build`` onward.
        """
        self._allow("has_parameter", "build", "prepend", "load", "process")
        return self._state.parameter_bag.has(name)

    def get_parameter_bag(self) -> EnvPlaceholderParameterBag:
        """Return the parameters of the build, merged, as stored.

        ``%name%`` references are resolved by ``ResolveParameterPlaceHoldersPass``.
        """
        return self._state.parameter_bag

    def remove(self, service: type, /, *, qualifier: Hashable | None = None) -> None:
        """Remove the service ``(service, qualifier)``.

        Raises:
            UnknownServiceError: If no such service is defined.
        """
        self._allow("remove", "process")
        definition = self._require((service, qualifier), "remove")
        self._state.store.remove(definition.key)

    def _require(self, key: ServiceKey, operation: str) -> Definition:
        definition = self._state.store.get(key)
        if definition is None:
            raise UnknownServiceError(key, operation)
        return definition

    def _allow(self, operation: str, *phases: Phase) -> None:
        # Local import mirrors the pattern in ServiceConfigurator to avoid a
        # circular import at module load time.
        from xtr_dependency_injection.exception import (  # noqa: PLC0415
            BuilderFrozenError,
            BuilderPhaseError,
        )

        phase = self._state.phase
        if phase == "frozen":
            raise BuilderFrozenError(operation)
        if phase not in phases:
            raise BuilderPhaseError(operation, phase)
