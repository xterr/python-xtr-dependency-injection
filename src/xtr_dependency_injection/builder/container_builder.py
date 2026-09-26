"""What bundle hooks and ``@compiler_pass`` receive: a view of the container being built.

By now every bundle has loaded and autoconfiguration has run, so a pass sees
the whole container — what exists, which config each bundle resolved — and
may still add, remove or mutate definitions. Earlier phases (``build``,
``prepend_extension``, ``load_extension``) also receive one, but with
narrower operations.

Named after Symfony's ``ContainerBuilder``.
"""

from __future__ import annotations

import inspect
from collections.abc import Mapping
from typing import TYPE_CHECKING, Final, TypeVar, cast, final, overload

from xtr_dependency_injection.exception import (
    ConfigProviderError,
    MissingBundleError,
    ParameterNotFoundError,
    UnknownConfigTypeError,
    UnknownServiceError,
)
from xtr_dependency_injection.exception._naming import qualified_name

from .autoconfigurator import Apply, Autoconfigurator, Reader
from .autoconfigure_rule import AutoconfigureRule
from .conflict_policy import record_alias
from .definition import Definition, Lifetime, Origin, ServiceKey
from .pass_stage import PassStage
from .service_configurator import BuildState, CompilerPassRequest, Kind, Phase, Prepend

if TYPE_CHECKING:
    from collections.abc import Callable, Hashable, Sequence

__all__ = ["ContainerBuilder", "kind_of"]

C = TypeVar("C")


def kind_of(provider: object) -> Kind:
    """Return how ``provider`` is registered, judged from what it is."""
    if isinstance(provider, type):
        return "class"
    if inspect.isfunction(provider):
        return "factory"
    return "instance"


@final
class ContainerBuilder:
    """A whole-container view for a bundle or a compiler pass.

    In phase ``build``, only parameter reads/writes, container queries,
    :meth:`register_for_autoconfiguration` and :meth:`register_attribute_for_autoconfiguration`
    are allowed. In phase ``prepend``, additionally
    :meth:`prepend_extension_config`. In phase ``load`` and ``process``,
    definition/alias/tag mutations too. Named after Symfony's
    ``ContainerBuilder`` — see the module docstring.
    """

    __slots__: tuple[str, ...] = ("_origin", "_state")

    _state: BuildState
    _origin: Origin

    def __init__(self, state: BuildState, origin: Origin) -> None:
        """Bind this builder to ``state`` as ``origin``."""
        self._state = state
        self._origin = origin

    def has(self, service: type, /, qualifier: Hashable | None = None) -> bool:
        """Return whether a definition or alias exists for ``(service, qualifier)``.

        Named after Symfony's ``ContainerBuilder::has``.
        """
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

        Named after Symfony's ``ContainerBuilder::register``. Allowed in
        phases ``load`` and ``process``.
        """
        self._allow("register", "load", "autoconfigure", "process")
        key: ServiceKey = (service, qualifier)
        definition = Definition(key, service, "class", lifetime, self._origin)
        self._state.store.add(definition)
        return definition

    def set_definition(self, definition: Definition, /) -> Definition:
        """Overwrite the definition of ``definition.key`` with ``definition``.

        Named after Symfony's ``ContainerBuilder::setDefinition``. Allowed
        in phases ``load`` and ``process``. Records the previous origin as
        an override.
        """
        self._allow("set_definition", "load", "autoconfigure", "process")
        existing = self._state.store.get(definition.key)
        if existing is None:
            self._state.store.add(definition)
        else:
            self._state.store.overwrite(definition)
        return definition

    def get_definition(self, service: type, /, qualifier: Hashable | None = None) -> Definition:
        """Return the definition of ``(service, qualifier)``.

        Named after Symfony's ``ContainerBuilder::getDefinition``.

        Raises:
            UnknownServiceError: If no such definition exists.
        """
        return self._require((service, qualifier), "get_definition")

    def has_definition(self, service: type, /, qualifier: Hashable | None = None) -> bool:
        """Return whether the definition of ``(service, qualifier)`` exists.

        Named after Symfony's ``ContainerBuilder::hasDefinition`` — unlike
        :meth:`has`, this does not follow aliases.
        """
        return self._state.store.get((service, qualifier)) is not None

    def find_definition(self, service: type, /, qualifier: Hashable | None = None) -> Definition:
        """Return the definition ``(service, qualifier)`` resolves to, following aliases.

        Named after Symfony's ``ContainerBuilder::findDefinition``.

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

        Named after Symfony's ``ContainerBuilder::removeDefinition``.

        Raises:
            UnknownServiceError: If no such definition exists.
        """
        self._allow("remove_definition", "load", "autoconfigure", "process")
        definition = self._require((service, qualifier), "remove_definition")
        self._state.store.remove(definition.key)

    def get_definitions(self) -> tuple[Definition, ...]:
        """Return every definition, in declaration order.

        Named after Symfony's ``ContainerBuilder::getDefinitions``.
        """
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

        Named after Symfony's ``ContainerBuilder::setAlias``. Allowed in
        phases ``load`` and ``process``.
        """
        self._allow("set_alias", "load", "autoconfigure", "process")
        record_alias(
            self._state.aliases,
            self._state.alias_origins,
            (alias, alias_qualifier),
            (target, target_qualifier),
            self._origin,
        )

    def get_alias(self, alias: type, /, qualifier: Hashable | None = None) -> ServiceKey:
        """Return the target key for ``(alias, qualifier)``.

        Named after Symfony's ``ContainerBuilder::getAlias``.

        Raises:
            UnknownServiceError: If no such alias exists.
        """
        key: ServiceKey = (alias, qualifier)
        target = self._state.aliases.get(key)
        if target is None:
            raise UnknownServiceError(key, "get_alias")
        return target

    def has_alias(self, alias: type, /, qualifier: Hashable | None = None) -> bool:
        """Return whether ``(alias, qualifier)`` is aliased to another key.

        Named after Symfony's ``ContainerBuilder::hasAlias``.
        """
        return (alias, qualifier) in self._state.aliases

    def remove_alias(self, alias: type, /, qualifier: Hashable | None = None) -> None:
        """Remove the alias ``(alias, qualifier)``.

        Named after Symfony's ``ContainerBuilder::removeAlias``.

        Raises:
            UnknownServiceError: If no such alias exists.
        """
        self._allow("remove_alias", "load", "autoconfigure", "process")
        key: ServiceKey = (alias, qualifier)
        if key not in self._state.aliases:
            raise UnknownServiceError(key, "remove_alias")
        del self._state.aliases[key]
        _ = self._state.alias_origins.pop(key, None)

    def find_tagged_service_ids(self, tag: str, /) -> dict[ServiceKey, list[dict[str, object]]]:
        """Return every definition tagged ``tag``, mapped to its attribute list.

        Named after Symfony's ``ContainerBuilder::findTaggedServiceIds``.
        Definition order.
        """
        return {
            definition.key: definition.get_tag(tag)
            for definition in self._state.store.entries()
            if definition.has_tag(tag)
        }

    def add_compiler_pass(
        self,
        fn: Callable[[ContainerBuilder], object],
        /,
        *,
        stage: PassStage = PassStage.BEFORE_OPTIMIZATION,
        priority: int = 0,
    ) -> None:
        """Register a compiler pass to run in ``stage`` at ``priority``.

        Named after Symfony's ``ContainerBuilder::addCompilerPass``. Only
        allowed in phase ``build`` (from :meth:`Bundle.build`). Passes
        registered here run after the bundle's own ``process`` (Symfony
        8.1 bundle-as-CompilerPass) and before the application's scanned
        ``@compiler_pass`` functions.
        """
        self._allow("add_compiler_pass", "build")
        self._state.compiler_passes.append(
            CompilerPassRequest(
                fn=cast("Callable[[object], object]", fn),
                stage=stage,
                priority=priority,
                order=len(self._state.compiler_passes),
                origin=self._origin,
                description=qualified_name(fn),
            )
        )

    def register_for_autoconfiguration(self, type_: type, /) -> AutoconfigureRule:
        """Return an :class:`AutoconfigureRule` for every subclass of ``type_``.

        Named after Symfony's ``ContainerBuilder::registerForAutoconfiguration``.
        Allowed in phases ``build`` and ``load``. The kernel's autoconfigure
        step applies each rule to every non-kernel definition whose built
        type has ``type_`` in its ``__mro__`` (nominal, matching Symfony's
        ``instanceof``). A tag already carried on a definition wins over the
        rule's — explicit stays.
        """
        self._allow("register_for_autoconfiguration", "build", "load")
        rule = AutoconfigureRule(type_=type_)
        self._state.autoconfigure_rules.append(rule)
        return rule

    def register_attribute_for_autoconfiguration(self, reader: Reader, callback: Apply, /) -> None:
        """Register a callback the kernel calls for every metadata item ``reader`` finds.

        Named after Symfony's ``ContainerBuilder::registerAttributeForAutoconfiguration``.
        The callback runs in the autoconfigure step with the registering
        bundle's :class:`ServiceConfigurator`.
        """
        self._allow(
            "register_attribute_for_autoconfiguration",
            "build",
            "prepend",
            "load",
            "autoconfigure",
            "process",
        )
        self._state.autoconfigurators.append(Autoconfigurator(self._origin.name, reader, callback))

    def set_parameter(self, name: str, value: object, /) -> None:
        """Set the parameter ``name`` to ``value``.

        Named after Symfony's ``ContainerBuilder::setParameter``. Merges
        into the parameter sources under this builder's origin; a leaf set
        twice by non-``app`` sources with a different value raises
        :class:`ParameterConflictError` at parameter-merge time.
        """
        self._allow("set_parameter", "build", "prepend", "load", "autoconfigure", "process")
        parts = name.split(".")
        nested: dict[str, object] = {parts[-1]: value}
        for part in reversed(parts[:-1]):
            nested = {part: nested}
        self._state.parameters.append((self._origin, nested))

    @overload
    def get_extension_config(self, bundle: str, /) -> object: ...
    @overload
    def get_extension_config(self, bundle: type[C], /) -> C: ...
    def get_extension_config(self, bundle: str | type[C], /) -> object:
        """Return the resolved config of a bundle, by name or by config type.

        Named after Symfony's ``ContainerBuilder::getExtensionConfig``.

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

        Named after Symfony's ``ContainerBuilder::prependExtensionConfig``.
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

        Allowed from phase ``build`` onward. Named after Symfony's
        ``ContainerBuilder::getParameter``.

        Raises:
            ParameterNotFoundError: If the parameter is not set.
        """
        self._allow("get_parameter", "build", "prepend", "load", "autoconfigure", "process")
        found, value = _lookup_parameter(self._state.parameters, name)
        if not found:
            raise ParameterNotFoundError(name)
        return value

    def has_parameter(self, name: str, /) -> bool:
        """Return whether the parameter ``name`` is defined.

        Allowed from phase ``build`` onward. Named after Symfony's
        ``ContainerBuilder::hasParameter``.
        """
        self._allow("has_parameter", "build", "prepend", "load", "autoconfigure", "process")
        found, _ = _lookup_parameter(self._state.parameters, name)
        return found

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


def _lookup_parameter(
    sources: Sequence[tuple[Origin, Mapping[str, object]]], name: str
) -> tuple[bool, object]:
    """Read a dotted-name parameter from ``(origin, mapping)`` sources, last-write wins."""
    parts = name.split(".")
    found = False
    value: object = None
    for _origin, values in sources:
        current: object = values
        matched = True
        for part in parts:
            step = _step_into(current, part)
            if step is _MISSING:
                matched = False
                break
            current = step
        if matched:
            found = True
            value = current
    return found, value


_MISSING: Final = object()


def _step_into(current: object, key: str) -> object:
    """Return ``current[key]`` when ``current`` is a mapping with ``key``, else ``_MISSING``."""
    if not isinstance(current, Mapping):
        return _MISSING
    mapping = cast("Mapping[str, object]", current)
    if key not in mapping:
        return _MISSING
    return mapping[key]
