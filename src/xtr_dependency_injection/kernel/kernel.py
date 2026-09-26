r"""The kernel: one line for the application, the whole build behind it.

``Kernel("app")`` does no work; it is a recipe. ``build()`` runs every step
below, in order, and returns a compiled container — each call independent of
the last, so tests and several kernels in one process never share a
container. Names and semantics follow Symfony 8.2's
``Symfony\Component\DependencyInjection\Kernel``:

1. environment — ``APP_ENV`` / ``APP_DEBUG`` or the arguments;
2. bundles — activation from ``bundles.py`` + ``@required_bundle``, in order;
3. early scan — the application's resources and the bundles';
4. ``build`` — every bundle's ``build(builder)``, in bundle order;
5. configs — defaults, application base providers, prepends collected from
   every bundle's ``prepend_extension(builder)``, and application transforms;
6. ``load_extension`` — every bundle defines its services from its resolved config;
7. late scan — what bundles asked to scan while loading;
8. marked definitions — what carries ``@as_service`` / ``@as_alias``;
9. autoconfigure — bundles react to every scanned candidate;
10. compiler passes — every bundle's ``process`` and the ``@compiler_pass`` functions;
11. compile — the wireup container.
"""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import inspect
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Final, Literal, cast, final

from xtr_dependency_injection.builder.autoconfigurator import run_autoconfigurators
from xtr_dependency_injection.builder.autoconfigure_rule import AutoconfigureRule
from xtr_dependency_injection.builder.conflict_policy import record_alias
from xtr_dependency_injection.builder.container_builder import ContainerBuilder
from xtr_dependency_injection.builder.definition import Definition, Origin, ServiceKey
from xtr_dependency_injection.builder.pass_stage import PassStage
from xtr_dependency_injection.builder.service_configurator import (
    BuildState,
    CompilerPassRequest,
    ServiceConfigurator,
)
from xtr_dependency_injection.bundle import KERNEL_BUNDLE, NoConfig
from xtr_dependency_injection.bundle.bundle import AnyBundle, Bundle
from xtr_dependency_injection.bundle.bundle_resolver import resolve_bundles
from xtr_dependency_injection.compiler._wireup_bridge import built_type, key_type
from xtr_dependency_injection.compiler.registration import _alias_factory, _null_decorator_factory
from xtr_dependency_injection.compiler.wireup_compiler import (
    Decoration,
    compile_container,
    emission_order,
    emit_injectables,
)
from xtr_dependency_injection.config.config_resolver import ResolvedConfigs, resolve_configs
from xtr_dependency_injection.config.env import env as read_env
from xtr_dependency_injection.config.parameters import call_parameters, merge_parameters
from xtr_dependency_injection.decorator.as_alias import aliases_of
from xtr_dependency_injection.decorator.as_decorator import (
    DecoratedParameter,
    OnInvalid,
    decorated_parameter_of,
    decorator_of,
)
from xtr_dependency_injection.decorator.as_service import service_of
from xtr_dependency_injection.decorator.as_tagged_item import tagged_item_of
from xtr_dependency_injection.decorator.autoconfigure import (
    AutoconfigureMarker,
    autoconfigure_of,
    autoconfigure_tags_of,
)
from xtr_dependency_injection.decorator.compiler_pass import compiler_pass_of
from xtr_dependency_injection.decorator.lifecycle import on_boot_of, on_shutdown_of
from xtr_dependency_injection.decorator.remove_if_missing import (
    REMOVE_IF_MISSING_TAG,
)
from xtr_dependency_injection.decorator.remove_if_missing import (
    markers_of as remove_if_missing_markers_of,
)
from xtr_dependency_injection.diagnostics import DefinitionReport
from xtr_dependency_injection.diagnostics.report import KernelReport, ReportBuilder
from xtr_dependency_injection.exception import (
    BundleDefinitionError,
    ConfigProviderError,
    DecoratorSignatureError,
    InvalidEnvironmentError,
    ResourceImportError,
    UnknownServiceError,
)
from xtr_dependency_injection.exception._naming import key_name as _naming_key_name
from xtr_dependency_injection.exception._naming import qualified_name
from xtr_dependency_injection.scan.default_excludes import DEFAULT_EXCLUDES
from xtr_dependency_injection.scan.scanned_object import ScannedObject
from xtr_dependency_injection.scan.scanner import Scanner, ScanResult

from .booted_kernel import BootedKernel, call_injected
from .compiled_kernel import CompiledKernel
from .kernel_bundle import KernelBundle

if TYPE_CHECKING:
    from collections.abc import Awaitable, Sequence

__all__ = [
    "Assembly",
    "Kernel",
    "Prepared",
    "assemble",
    "collect_compiler_passes",
    "definition_reports",
    "prepare",
    "remove_if_missing_pass",
    "resolve_decorations_pass",
    "validate_aliases_pass",
]


@final
class Kernel:
    """An application's kernel: which bundles, which resources, which environment.

    Constructing one stores its arguments and nothing else; ``build``,
    ``boot`` and ``run`` do the work, each time afresh.
    """

    __slots__ = (
        "_allowed_envs",
        "_bundles",
        "_concurrent_scoped_access",
        "_debug",
        "_env",
        "_exclude",
        "_name",
        "_package",
        "_resources",
    )

    def __init__(  # noqa: PLR0913 — each argument is a separate, optional decision.
        self,
        package: str | ModuleType,
        /,
        *,
        env: str | None = None,
        debug: bool | None = None,
        name: str | None = None,
        bundles: Mapping[type[AnyBundle], Mapping[str, bool]] | None = None,
        resources: Sequence[str] | None = None,
        exclude: Sequence[str] = DEFAULT_EXCLUDES,
        allowed_envs: Sequence[str] | None = None,
        concurrent_scoped_access: bool = False,
    ) -> None:
        """Store the kernel's recipe.

        Args:
            package: The application package, scanned recursively.
            env: The environment; default ``APP_ENV``, else ``"dev"``.
            debug: Debug mode; default ``APP_DEBUG``, else true outside
                ``"prod"``.
            name: The application's name; default the package's last
                component.
            bundles: The bundle classes the application lists, mapped to
                their per-environment activity flags (``{"all": True}`` or
                ``{"dev": True}``). When ``None`` the kernel imports
                ``<package>.bundles`` and reads its ``BUNDLES`` mapping.
            resources: What to scan instead of ``package``.
            exclude: ``fnmatch`` patterns of modules never scanned;
                replaces ``DEFAULT_EXCLUDES``.
            allowed_envs: The only environments the kernel accepts.
            concurrent_scoped_access: Passed to wireup.
        """
        self._package = package
        self._env = env
        self._debug = debug
        self._name = name
        self._bundles: Mapping[type[AnyBundle], Mapping[str, bool]] | None = (
            dict(bundles) if bundles is not None else None
        )
        self._resources = tuple(resources) if resources is not None else None
        self._exclude = tuple(exclude)
        self._allowed_envs = tuple(allowed_envs) if allowed_envs is not None else None
        self._concurrent_scoped_access = concurrent_scoped_access

    @property
    def name(self) -> str:
        """The application's name."""
        return self._name if self._name is not None else self._package_name.rsplit(".", 1)[-1]

    @property
    def environment(self) -> str:
        """The environment: the argument, else ``APP_ENV``, else ``"dev"``."""
        return self._env if self._env is not None else os.environ.get("APP_ENV", "dev")

    @property
    def debug(self) -> bool:
        """Debug mode: the argument, else ``APP_DEBUG``, else true outside ``"prod"``."""
        if self._debug is not None:
            return self._debug
        return read_env("APP_DEBUG", bool, default=self.environment != "prod")

    @property
    def project_dir(self) -> Path:
        """The nearest directory above the package with a ``pyproject.toml``; else the package's."""
        package_dir = _package_dir(self._package)
        for directory in (package_dir, *package_dir.parents):
            if (directory / "pyproject.toml").is_file():
                return directory
        return package_dir

    def with_env(self, env: str, /, *, debug: bool | None = None) -> Kernel:
        """Return the same recipe for another environment.

        An explicit debug carries over unless overridden.
        """
        return Kernel(
            self._package,
            env=env,
            debug=debug if debug is not None else self._debug,
            name=self._name,
            bundles=self._bundles,
            resources=self._resources,
            exclude=self._exclude,
            allowed_envs=self._allowed_envs,
            concurrent_scoped_access=self._concurrent_scoped_access,
        )

    def build(self) -> CompiledKernel:
        """Run steps 1 to 11 and return the compiled container, not yet booted."""
        environment, debug = self.environment, self.debug
        _check_environment(environment, self._allowed_envs)
        listed = (
            self._bundles if self._bundles is not None else _load_bundles_module(self._package_name)
        )
        prepared = prepare(
            name=self.name,
            environment=environment,
            debug=debug,
            project_dir=self.project_dir,
            listed=listed,
            resources=self._resources if self._resources is not None else (self._package,),
            exclude=self._exclude,
        )
        state = prepared.assembly.state
        parameters = merge_parameters(
            [
                *((str(origin), values) for origin, values in state.parameters),
                *(
                    (scanned.name, call_parameters(cast("Callable[..., object]", scanned.obj)))
                    for scanned in prepared.assembly.parameter_providers
                ),
            ]
        )
        container = compile_container(
            prepared.injectables,
            prepared.ordered,
            parameters=parameters,
            concurrent_scoped_access=self._concurrent_scoped_access,
        )
        frozen = prepared.finish_report()
        return CompiledKernel(
            container,
            frozen,
            info=prepared.core.info,
            bundles=prepared.bundles,
            on_boot=prepared.assembly.on_boot,
            on_shutdown=prepared.assembly.on_shutdown,
        )

    async def boot(self) -> BootedKernel:
        """Build, then boot: bundles in order, then ``@on_boot`` hooks."""
        return await self.build().boot()

    def run(self, main: Callable[..., Awaitable[int] | int], /) -> int:
        """Boot, call ``main`` with its ``Injected[...]`` filled, shut down, return its exit code.

        Raises:
            TypeError: If ``main`` returns anything but an ``int``.
        """
        return asyncio.run(self._run(main))

    async def _run(self, main: Callable[..., Awaitable[int] | int]) -> int:
        async with await self.boot() as booted:
            result = await call_injected(booted._engine, main)  # noqa: SLF001 — the kernel owns the engine.  # pyright: ignore[reportPrivateUsage]
        if not isinstance(result, int) or isinstance(result, bool):
            msg = f"{getattr(main, '__qualname__', main)!r} returned {result!r}, not an exit code"
            raise TypeError(msg)
        return result

    @property
    def _package_name(self) -> str:
        return self._package if isinstance(self._package, str) else self._package.__name__


@dataclass(frozen=True, slots=True)
class Assembly:
    """What steps 3 to 10 produce: a frozen build state, ready to compile.

    Attributes:
        state: The definitions, parameters and requests of the build.
        decorations: Validated decorations per decorated key.
        parameter_providers: The application's ``@parameters`` functions.
        on_boot: ``@on_boot`` hooks, in the order they run.
        on_shutdown: ``@on_shutdown`` hooks, in the order they run.
    """

    state: BuildState
    decorations: dict[ServiceKey, list[Decoration]]
    parameter_providers: list[ScannedObject]
    on_boot: list[Callable[..., object]]
    on_shutdown: list[Callable[..., object]]


def assemble(  # noqa: PLR0913 — steps 3 to 10 need all of these.
    *,
    name: str,
    bundles: Sequence[AnyBundle],
    active: Sequence[str],
    inactive_config_owners: Mapping[type, str],
    resources: Sequence[str | ModuleType],
    environment: str,
    debug: bool,
    project_dir: Path,
    exclude: Sequence[str],
    report: ReportBuilder,
    given: Sequence[object] = (),
) -> Assembly:
    """Run steps 3 to 10 for ``bundles``, recording into ``report``.

    Shared by :func:`prepare`, which computes ``active`` once for both the
    report and this call.
    """
    scanner = Scanner(env=environment, exclude=exclude)
    early = _early_scan(scanner, resources, bundles)
    state = BuildState(env=environment, debug=debug, bundles=tuple(active), configs={})
    _register_kernel_parameters(
        state,
        name=name,
        environment=environment,
        debug=debug,
        project_dir=project_dir,
        bundles=bundles,
    )
    _build(state, bundles)
    _run_prepend_extension(state, bundles)
    configs = _configs(
        bundles,
        early,
        inactive_config_owners,
        environment,
        given=given,
        prepends=state.prepends,
    )
    report.configs.extend(configs.reports)
    report.skipped.extend(configs.skipped)
    state.configs = configs.values
    _load(state, bundles, configs)
    late = _late_scan(scanner, state)
    _marked(state, [*early.marked, *late.marked])
    _autoconfigure(state, [*early.services, *late.services])
    _run_compiler_passes(
        state,
        bundles,
        [*early.compiler_passes, *late.compiler_passes],
        [*early.decorators, *late.decorators],
    )
    report.modules.extend(scanner.modules)
    report.skipped.extend(scanner.skipped)
    return Assembly(
        state=state,
        decorations=state.decorations,
        parameter_providers=list(early.parameters),
        on_boot=_hooks([*early.on_boot, *late.on_boot], on_boot_of),
        on_shutdown=_hooks([*early.on_shutdown, *late.on_shutdown], on_shutdown_of),
    )


@dataclass(frozen=True, slots=True)
class Prepared:
    """Everything ready to compile, shared by :meth:`Kernel.build` and ``injectables()``.

    Attributes:
        core: The kernel bundle, its info identified and bundles activated.
        report: The report so far — bundles, configs, modules; definitions are
            added by :meth:`finish_report`.
        bundles: The active bundle instances, in dependency order.
        assembly: What steps 3 to 10 produced.
        ordered: The definitions in emission order.
        injectables: The wireup injectables realizing them.
    """

    core: KernelBundle
    report: ReportBuilder
    bundles: tuple[AnyBundle, ...]
    assembly: Assembly
    ordered: list[Definition]
    injectables: list[object]

    def finish_report(self) -> KernelReport:
        """Add the definitions, freeze the report, attach it to the kernel info, and return it."""
        self.report.definitions.extend(
            definition_reports(self.assembly.state, self.ordered, self.assembly.decorations)
        )
        frozen = self.report.freeze()
        self.core.info.attach(frozen)
        return frozen


def prepare(  # noqa: PLR0913 — each input is a separate build decision.
    *,
    name: str,
    environment: str,
    debug: bool,
    project_dir: Path,
    listed: Mapping[type[AnyBundle], Mapping[str, bool]],
    resources: Sequence[str | ModuleType],
    exclude: Sequence[str],
    given: Sequence[object] = (),
) -> Prepared:
    """Run steps 1's aftermath through 10, then emit: the pipeline both entry points share.

    Chooses the bundles, records them, assembles the definitions, orders them
    and emits the wireup injectables — everything up to but not including the
    parameter merge and the container compilation, which the two entry points
    do differently.
    """
    core = KernelBundle()
    core.info.identify(name=name, environment=environment, debug=debug, project_dir=project_dir)
    report = ReportBuilder()
    resolved = resolve_bundles(core=core, listed=listed, env=environment)
    active = [type(bundle).metadata().name for bundle in resolved.bundles]
    core.info.activate(active)
    report.bundles.extend(resolved.reports)
    inactive_config_owners = _inactive_config_owners(listed, active)
    assembly = assemble(
        name=name,
        bundles=resolved.bundles,
        active=active,
        inactive_config_owners=inactive_config_owners,
        resources=resources,
        environment=environment,
        debug=debug,
        project_dir=project_dir,
        exclude=exclude,
        report=report,
        given=given,
    )
    ordered = emission_order(assembly.state.store.entries())
    injectables = emit_injectables(ordered, assembly.decorations, core.resetter.track)
    return Prepared(
        core=core,
        report=report,
        bundles=resolved.bundles,
        assembly=assembly,
        ordered=ordered,
        injectables=injectables,
    )


def _check_environment(environment: str, allowed: Sequence[str] | None) -> None:
    """Step 1: check the environment against the allowed ones.

    Step 2, the bundles, is ``resolve_bundles`` itself.

    Raises:
        InvalidEnvironmentError: If the environment is not allowed.
    """
    if allowed is not None and environment not in allowed:
        raise InvalidEnvironmentError(environment, tuple(allowed))


def _early_scan(
    scanner: Scanner, resources: Sequence[str | ModuleType], bundles: Sequence[AnyBundle]
) -> ScanResult:
    """Step 3: the application's resources, then each active bundle's."""
    merged = scanner.scan(resources, owner=None)
    for bundle in bundles:
        metadata = type(bundle).metadata()
        if metadata.resources:
            merged.extend(scanner.scan(metadata.resources, owner=metadata.name))
    return merged


def _configs(  # noqa: PLR0913 — every input feeds resolve_configs directly.
    bundles: Sequence[AnyBundle],
    early: ScanResult,
    inactive: Mapping[type, str],
    environment: str,
    *,
    given: Sequence[object] = (),
    prepends: Sequence[object] = (),
) -> ResolvedConfigs:
    """Step 5: every bundle's resolved config, given the prepends already recorded."""
    from xtr_dependency_injection.builder.service_configurator import Prepend  # noqa: PLC0415

    return resolve_configs(
        bundles=bundles,
        providers=early.configure,
        inactive=inactive,
        env=environment,
        given=given,
        prepends=cast("Sequence[Prepend]", prepends),
    )


def _build(state: BuildState, bundles: Sequence[AnyBundle]) -> None:
    """Step 4: every bundle's ``build(builder)``, in order."""
    state.phase = "build"
    for bundle in bundles:
        origin = _origin_of(type(bundle).metadata().name)
        bundle.build(ContainerBuilder(state, origin))


def _run_prepend_extension(state: BuildState, bundles: Sequence[AnyBundle]) -> None:
    """Step 5a: every bundle's ``prepend_extension(builder)``, in order."""
    state.phase = "prepend"
    for bundle in bundles:
        origin = _origin_of(type(bundle).metadata().name)
        bundle.prepend_extension(ContainerBuilder(state, origin))


def _register_kernel_parameters(  # noqa: PLR0913 — the kernel identity is a fixed 5-field shape.
    state: BuildState,
    *,
    name: str,
    environment: str,
    debug: bool,
    project_dir: Path,
    bundles: Sequence[AnyBundle],
) -> None:
    """Register the ``kernel.*`` parameters into ``state`` before any bundle's ``build`` runs.

    Symfony 8.2 exposes ``kernel.name``, ``kernel.environment``, ``kernel.debug``,
    ``kernel.project_dir`` and ``kernel.bundles`` (name → class) from the very
    beginning of the container build; every bundle's hook may read them.
    """
    bundles_map = {type(bundle).metadata().name: qualified_name(type(bundle)) for bundle in bundles}
    state.parameters.append(
        (
            Origin("kernel", KERNEL_BUNDLE),
            {
                KERNEL_BUNDLE: {
                    "name": name,
                    "environment": environment,
                    "debug": debug,
                    "project_dir": str(project_dir),
                    "bundles": bundles_map,
                }
            },
        )
    )


def _inactive_config_owners(
    listed: Mapping[type[AnyBundle], Mapping[str, bool]],
    active: Sequence[str],
) -> Mapping[type, str]:
    """Return a mapping ``config_type -> bundle name`` for listed but env-disabled bundles."""
    result: dict[type, str] = {}
    for bundle_type in listed:
        metadata = bundle_type.metadata()
        if metadata.name in active:
            continue
        if metadata.config is NoConfig:
            continue
        result[metadata.config] = metadata.name
    return result


def _load(state: BuildState, bundles: Sequence[AnyBundle], configs: ResolvedConfigs) -> None:
    """Step 6: every bundle's ``load_extension``, in order.

    Right after the kernel bundle loads (its info and resetter), the kernel
    registers every active bundle's resolved non-``NoConfig`` config under its
    type, so any service can inject it — preserving the emission order of
    info, resetter, then configs.
    """
    state.phase = "load"
    for bundle in bundles:
        name = type(bundle).metadata().name
        origin = _origin_of(name)
        services = ServiceConfigurator(state, origin)
        builder = ContainerBuilder(state, origin)
        bundle.load_extension(configs.values[name], services, builder)
        if name == KERNEL_BUNDLE:
            _register_configs(state, configs.values)


def _register_configs(state: BuildState, values: Mapping[str, object]) -> None:
    """Register every resolved non-``NoConfig`` config under its type, as the kernel."""
    services = ServiceConfigurator(state, _origin_of(KERNEL_BUNDLE))
    for value in values.values():
        if not isinstance(value, NoConfig):
            _ = services.instance(value)


def _late_scan(scanner: Scanner, state: BuildState) -> ScanResult:
    """Step 6: what bundles asked to scan while loading."""
    merged = ScanResult()
    for owner, resources in state.late_scans:
        merged.extend(scanner.scan(resources, owner=owner, late=True))
    return merged


def _marked(state: BuildState, marked: Sequence[ScannedObject]) -> None:
    """Step 7b: definitions for objects carrying ``@as_service`` or ``@as_alias``.

    Runs alongside the existing wireup-``@injectable`` path (which todo 14c
    will remove). Each object becomes exactly one definition under its own
    type + qualifier; every ``@as_alias(Iface)`` records an alias
    ``(Iface, ...) -> (own_type, own_qualifier)`` in the build state.
    """
    for scanned in marked:
        obj = scanned.obj
        service = service_of(obj)
        aliases = aliases_of(obj)
        origin = (
            Origin("app", scanned.name)
            if scanned.owner is None
            else Origin("bundle", scanned.owner, f"marked by {scanned.name}")
        )
        if inspect.isclass(obj):
            own_type = obj
            kind: Literal["class", "factory"] = "class"
        elif inspect.isfunction(obj):
            own_type = key_type(cast("Callable[..., object]", obj), None)
            kind = "factory"
        else:  # pragma: no cover — the scanner queues only classes and functions.
            continue
        lifetime = service.lifetime if service is not None else "singleton"
        qualifier = service.qualifier if service is not None else None
        own_key: ServiceKey = (own_type, qualifier)
        existing = state.store.get(own_key)
        if existing is None or existing.provider is not obj:
            tagged = tagged_item_of(obj)
            definition = Definition(own_key, obj, kind, lifetime, origin)
            if tagged is not None:
                definition.priority = tagged.priority
                definition.before = tagged.before
                definition.after = tagged.after
            state.store.add(definition)
        for marker in aliases:
            record_alias(
                state.aliases,
                state.alias_origins,
                (marker.alias, marker.qualifier),
                own_key,
                origin,
            )
        for attributes in remove_if_missing_markers_of(obj):
            definition = state.store.get(own_key)
            if definition is not None:
                _ = definition.add_tag(REMOVE_IF_MISSING_TAG, **attributes)


def _autoconfigure(state: BuildState, candidates: Sequence[ScannedObject]) -> None:
    """Step 9: attribute autoconfigurators + nominal ``register_for_autoconfiguration`` rules.

    Attribute-based autoconfigurators run first over every service candidate
    (Symfony ``registerAttributeForAutoconfiguration``); then the nominal
    rules (Symfony ``registerForAutoconfiguration`` — ``instanceof``) plus any
    ``@autoconfigure`` / ``@autoconfigure_tag`` markers on scanned classes
    apply to every non-kernel definition.
    """
    state.phase = "autoconfigure"

    def configurator_for(owner: str, candidate: ScannedObject) -> ServiceConfigurator:
        base = _origin_of(owner)
        origin = Origin(base.kind, base.name, f"via autoconfigure of {candidate.name}")
        return ServiceConfigurator(state, origin)

    run_autoconfigurators(state.autoconfigurators, candidates, configurator_for)
    _apply_autoconfigure_rules(state, candidates)


def _apply_autoconfigure_rules(state: BuildState, candidates: Sequence[ScannedObject]) -> None:
    """Apply every nominal autoconfigure rule to every non-kernel definition.

    Rules come from two sources:

    - ``ContainerBuilder.register_for_autoconfiguration`` — collected into
      ``state.autoconfigure_rules``.
    - ``@autoconfigure`` / ``@autoconfigure_tag`` markers on scanned classes —
      each class turns into a rule keyed on the class itself.

    A rule applies to a definition when the definition's built type has the
    rule's ``type_`` in its ``__mro__``. Kernel-origin definitions are never
    autoconfigured (Symfony parity); a tag already present on a definition
    wins over the rule's — explicit stays. When a rule carries ``factory``
    (from ``@autoconfigure(factory=…)``), a matched class definition becomes
    a factory definition using that factory.
    """
    rules: list[AutoconfigureRule] = list(state.autoconfigure_rules)
    marker_rules = _collect_marker_rules(candidates)
    rules.extend(rule for _marker, rule in marker_rules.values())
    factories: dict[type, Callable[..., object]] = {
        cls: marker.factory
        for cls, (marker, _rule) in marker_rules.items()
        if marker.factory is not None
    }
    if not rules and not factories:
        return
    for definition in list(state.store.entries()):
        if definition.origin.kind == "kernel":
            continue
        built = built_type(definition)
        if built is None:
            continue
        mro = built.__mro__
        for rule in rules:
            if rule.type_ not in mro:
                continue
            _apply_rule_to_definition(rule, definition, built)
        for cls, factory in factories.items():
            if cls in mro:
                _replace_with_factory(state, definition, factory, built)


def _collect_marker_rules(
    candidates: Sequence[ScannedObject],
) -> dict[type, tuple[AutoconfigureMarker, AutoconfigureRule]]:
    """Return a rule per scanned class carrying ``@autoconfigure`` or ``@autoconfigure_tag``."""
    collected: dict[type, tuple[AutoconfigureMarker, AutoconfigureRule]] = {}
    for candidate in candidates:
        obj = candidate.obj
        if not isinstance(obj, type):
            continue
        marker = autoconfigure_of(obj)
        tag_markers = autoconfigure_tags_of(obj)
        if marker is None and not tag_markers:
            continue
        rule = AutoconfigureRule(type_=obj)
        effective = marker if marker is not None else AutoconfigureMarker()
        if effective.lifetime is not None:
            rule.lifetime = effective.lifetime
        for entry in effective.tags:
            if isinstance(entry, str):
                rule.tags.setdefault(entry, []).append({})
            else:
                tag_name, attrs = entry
                rule.tags.setdefault(tag_name, []).append(_as_tag_attrs(attrs))
        for tm in tag_markers:
            name = tm.name if tm.name is not None else qualified_name(obj)
            rule.tags.setdefault(name, []).append(dict(tm.attributes))
        collected[obj] = (effective, rule)
    return collected


def _as_tag_attrs(attrs: object) -> dict[str, object]:
    """Normalize a tag-attribute value into a dict, deferring callables via a sentinel."""
    if callable(attrs) and not isinstance(attrs, Mapping):
        return {_CALLABLE_ATTRS: attrs}
    return dict(cast("Mapping[str, object]", attrs))


_CALLABLE_ATTRS: Final = "__xtr_autoconfigure_callable__"


def _apply_rule_to_definition(rule: AutoconfigureRule, definition: Definition, built: type) -> None:
    """Apply ``rule`` to ``definition`` in place — tags, lifetime."""
    for tag_name, attribute_list in rule.tags.items():
        if definition.has_tag(tag_name):
            continue
        for attrs in attribute_list:
            callable_attrs = attrs.get(_CALLABLE_ATTRS)
            if callable_attrs is not None:
                computed = cast("Callable[[type], Mapping[str, object]]", callable_attrs)(built)
                _ = definition.add_tag(tag_name, **dict(computed))
            else:
                _ = definition.add_tag(tag_name, **attrs)
    if rule.lifetime is not None:
        definition.lifetime = rule.lifetime


def _replace_with_factory(
    _state: BuildState,
    definition: Definition,
    factory: Callable[..., object],
    built: type,
) -> None:
    """Replace a matched class definition with a factory definition — Symfony 8.2 ``factory``.

    Validates that the factory's evaluated return type equals ``built``; else
    raises :class:`ConfigProviderError` with both types.
    """
    if definition.kind != "class":
        return
    returned = key_type(factory, None)
    if returned is not built:
        raise ConfigProviderError(
            qualified_name(factory),
            (
                f"@autoconfigure(factory=…) return type {qualified_name(returned)} "
                f"is not the matched class {qualified_name(built)}"
            ),
        )
    definition.provider = factory
    definition.kind = "factory"


def _run_compiler_passes(
    state: BuildState,
    bundles: Sequence[AnyBundle],
    scanned_passes: Sequence[ScannedObject],
    scanned_decorators: Sequence[ScannedObject],
) -> None:
    """Run every compiler pass, stage by stage, as Symfony's ``Compiler::compile`` does.

    Collection order (Symfony 8.1 bundle-as-CompilerPass + app + built-ins):
    for each active bundle in order — its ``process`` if the class overrides
    ``Bundle.process``, then whatever it added in ``build`` via
    ``builder.add_compiler_pass``; then the application's scanned
    ``@compiler_pass`` functions in scan order; then the built-in kernel
    passes. Execution follows :class:`PassStage` — one stage at a time —
    and within a stage by priority descending, ties by collection order.
    """
    state.phase = "process"
    requests = collect_compiler_passes(state, bundles, scanned_passes, scanned_decorators)
    for request in _sorted_passes(requests):
        _ = request.fn(ContainerBuilder(state, request.origin))


def collect_compiler_passes(
    state: BuildState,
    bundles: Sequence[AnyBundle],
    scanned_passes: Sequence[ScannedObject],
    scanned_decorators: Sequence[ScannedObject],
) -> list[CompilerPassRequest]:
    """Return every compiler pass to run, in collection order.

    Collection follows Symfony's ``PassConfig::getPasses``: bundles' own
    ``process`` (only when overridden), then the passes each bundle added
    via ``builder.add_compiler_pass``, then application ``@compiler_pass``
    functions in scan order, then the built-in kernel passes.
    """
    collected: list[CompilerPassRequest] = []

    def append(
        fn: Callable[[ContainerBuilder], object],
        *,
        stage: PassStage,
        priority: int,
        origin: Origin,
        description: str,
    ) -> None:
        collected.append(
            CompilerPassRequest(
                fn=cast("Callable[[object], object]", fn),
                stage=stage,
                priority=priority,
                order=len(collected),
                origin=origin,
                description=description,
            )
        )

    for bundle in bundles:
        name = type(bundle).metadata().name
        if type(bundle).process is not Bundle.process:
            append(
                bundle.process,
                stage=PassStage.BEFORE_OPTIMIZATION,
                priority=0,
                origin=_origin_of(name),
                description=f"{qualified_name(type(bundle))}.process",
            )
        origin_name = name
        for request in state.compiler_passes:
            if request.origin.name == origin_name and request.origin.kind != "app":
                collected.append(
                    CompilerPassRequest(
                        fn=request.fn,
                        stage=request.stage,
                        priority=request.priority,
                        order=len(collected),
                        origin=request.origin,
                        description=request.description,
                    )
                )
    for scanned in scanned_passes:
        marker = compiler_pass_of(scanned.obj)
        if marker is None:
            continue
        append(
            cast("Callable[[ContainerBuilder], object]", scanned.obj),
            stage=marker.stage,
            priority=marker.priority,
            origin=_scanned_origin(scanned),
            description=scanned.name,
        )
    kernel_origin = _origin_of(KERNEL_BUNDLE)
    append(
        lambda builder: resolve_decorations_pass(builder, scanned_decorators),
        stage=PassStage.OPTIMIZE,
        priority=0,
        origin=kernel_origin,
        description="kernel:resolve_decorations",
    )
    append(
        remove_if_missing_pass,
        stage=PassStage.BEFORE_REMOVING,
        priority=0,
        origin=kernel_origin,
        description="kernel:remove_if_missing",
    )
    append(
        validate_aliases_pass,
        stage=PassStage.AFTER_REMOVING,
        priority=0,
        origin=kernel_origin,
        description="kernel:validate_aliases",
    )
    return collected


def _sorted_passes(requests: Sequence[CompilerPassRequest]) -> list[CompilerPassRequest]:
    """Sort ``requests`` by stage, then priority descending, ties by collection order."""
    stage_order = {stage: index for index, stage in enumerate(PassStage)}
    return sorted(requests, key=lambda r: (stage_order[r.stage], -r.priority, r.order))


def resolve_decorations_pass(
    builder: ContainerBuilder, scanned_decorators: Sequence[ScannedObject]
) -> None:
    """OPTIMIZE built-in: build ``state.decorations`` from decoration requests.

    Reads every ``Definition.decorates`` set through ``set_decorated_service``
    and every scanned ``@as_decorator`` marker, sorts them by priority
    (highest wraps the original first), populates ``state.decorations`` and
    removes each decorator definition from its own key so the decorator lives
    only under the target's key (Symfony's ``DecoratorServicePass`` swaps the
    id).

    ``on_invalid`` (Symfony's ``AsDecorator::$onInvalid``) chooses what
    happens when the target is not defined:

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
    for request in sorted(requests, key=lambda r: (-r.priority, r.order)):
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
        requests.append(
            _PendingDecoration(
                key=(marker.target, marker.qualifier),
                decorator=cast("type | Callable[..., object]", scanned.obj),
                priority=marker.priority,
                on_invalid=marker.on_invalid,
                name=scanned.name,
                order=order,
                own_key=None,
                origin=_scanned_origin(scanned),
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


def remove_if_missing_pass(builder: ContainerBuilder) -> None:
    """BEFORE_REMOVING built-in: drop every definition whose ``container.remove_if_missing`` fails.

    Port of Symfony 8.2's ``RemoveMissingDependenciesPass`` (see
    ``.tmp/symfony/src/Symfony/Component/DependencyInjection/Compiler/RemoveMissingDependenciesPass.php``
    at commit ``5b23e4e``). A tag has ``service=<type>`` (with optional
    ``qualifier=``), ``class_="module:Class"`` and/or ``package="dist"``;
    every tag on a definition must hold, and every attribute of a tag must
    hold. Removing one definition can invalidate another's tag, so the pass
    sweeps until it settles. When a definition is dropped, any alias
    pointing at it is dropped too (Symfony parity).
    """
    state = builder._state  # noqa: SLF001  # pyright: ignore[reportPrivateUsage] — the built-in pass reads state directly.
    tagged: dict[ServiceKey, list[dict[str, object]]] = {
        definition.key: definition.get_tag(REMOVE_IF_MISSING_TAG)
        for definition in state.store.entries()
        if definition.has_tag(REMOVE_IF_MISSING_TAG)
    }
    if not tagged:
        return
    while True:
        removed = False
        for key in list(tagged):
            if state.store.get(key) is None:
                del tagged[key]
                continue
            for tag in tagged[key]:
                if _remove_if_missing_holds(state, tag):
                    continue
                _remove_with_aliases(state, key)
                del tagged[key]
                removed = True
                break
        if not removed:
            break


def _remove_if_missing_holds(state: BuildState, tag: Mapping[str, object]) -> bool:
    """Return whether every attribute of ``tag`` holds — Symfony's ``holds``."""
    service = tag.get("service")
    if service is not None:
        qualifier = tag.get("qualifier")
        if not _alias_or_definition_of(state, (cast("type", service), qualifier)):
            return False
    class_path = tag.get("class_")
    if class_path is not None and not _class_importable(cast("str", class_path)):
        return False
    package = tag.get("package")
    return not (package is not None and not _package_installed(cast("str", package)))


def _alias_or_definition_of(state: BuildState, key: ServiceKey) -> bool:
    """Return whether ``key`` resolves — follows aliases without looping."""
    seen: set[ServiceKey] = set()
    while key in state.aliases and key not in seen:
        seen.add(key)
        key = state.aliases[key]
    return state.store.get(key) is not None


def _class_importable(path: str) -> bool:
    """Return whether ``"module:Class"`` resolves — imports lazily and swallows failure."""
    module, _, attribute = path.partition(":")
    if not module or not attribute:
        return False
    try:
        loaded = importlib.import_module(module)
    except ImportError:
        return False
    return hasattr(loaded, attribute)


def _package_installed(name: str) -> bool:
    """Return whether ``name`` is an installed distribution."""
    # Local import to keep the module import graph minimal.
    from importlib.metadata import PackageNotFoundError, distribution  # noqa: PLC0415

    try:
        _ = distribution(name)
    except PackageNotFoundError:
        return False
    return True


def _remove_with_aliases(state: BuildState, key: ServiceKey) -> None:
    """Drop ``key`` from the store and every alias pointing at it (recursively)."""
    if state.store.get(key) is not None:
        state.store.remove(key)
    dangling = [alias for alias, target in state.aliases.items() if target == key]
    for alias in dangling:
        del state.aliases[alias]
        _ = state.alias_origins.pop(alias, None)
        _remove_with_aliases(state, alias)


def validate_aliases_pass(builder: ContainerBuilder) -> None:
    """AFTER_REMOVING built-in: turn each alias into a forwarding definition and freeze.

    Every ``(alias_key -> target_key)`` becomes a factory definition producing
    the target's instance under the alias key (Symfony's ``setAlias``). A
    missing target — a raised ``UnknownServiceError`` — means an
    ``@as_alias`` (or an explicit ``set_alias``/``alias``) that referred to
    a service that never existed, or that a preceding ``BEFORE_REMOVING``
    pass removed the target without dropping the alias.

    Raises:
        UnknownServiceError: If an alias target is not defined.
    """
    state = builder._state  # noqa: SLF001  # pyright: ignore[reportPrivateUsage] — the built-in pass reads state directly.
    for alias_key, target_key in state.aliases.items():
        if state.store.get(alias_key) is not None:
            continue
        target = state.store.get(target_key)
        if target is None:
            raise UnknownServiceError(alias_key, "set_alias")
        alias_type, alias_qualifier = alias_key
        target_type, target_qualifier = target_key
        factory = _alias_factory(alias_type, target_type, target_qualifier)
        state.store.add(
            Definition(
                key=(alias_type, alias_qualifier),
                provider=factory,
                kind="factory",
                lifetime=target.lifetime,
                origin=Origin(target.origin.kind, target.origin.name, "alias"),
            )
        )
    state.phase = "frozen"


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


def definition_reports(
    state: BuildState,
    ordered: Sequence[Definition],
    decorations: Mapping[ServiceKey, Sequence[Decoration]],
) -> list[DefinitionReport]:
    """Return what the report says of each definition, plus its tags and aliases."""
    aliases_of_target: dict[ServiceKey, list[str]] = {}
    for alias_key, target_key in state.aliases.items():
        aliases_of_target.setdefault(target_key, []).append(_naming_key_name(alias_key))
    return [
        DefinitionReport(
            key=definition.key,
            provider_qualname=qualified_name(
                type(definition.provider) if definition.kind == "instance" else definition.provider
            ),
            kind=definition.kind,
            lifetime=definition.lifetime,
            origin=definition.origin,
            overrides=state.store.overrides_of(definition.key),
            decorated_by=tuple(d.name for d in decorations.get(definition.key, ())),
            tags=tuple(definition.tags),
            aliases=tuple(aliases_of_target.get(definition.key, ())),
        )
        for definition in ordered
    ]


def _hooks(
    scanned: Sequence[ScannedObject], marker_of: Callable[[object], object]
) -> list[Callable[..., object]]:
    return [cast("Callable[..., object]", s.obj) for s in _by_priority(scanned, marker_of)]


def _by_priority(
    scanned: Sequence[ScannedObject], marker_of: Callable[[object], object]
) -> list[ScannedObject]:
    """Return ``scanned`` by marker priority, highest first, then scan order."""

    def priority(entry: ScannedObject) -> int:
        return cast("int", getattr(marker_of(entry.obj), "priority", 0))

    return sorted(scanned, key=lambda entry: (-priority(entry), entry.order))


def _origin_of(bundle: str) -> Origin:
    return Origin("kernel", bundle) if bundle == KERNEL_BUNDLE else Origin("bundle", bundle)


def _scanned_origin(scanned: ScannedObject) -> Origin:
    if scanned.owner is None:
        return Origin("app", scanned.name)
    return Origin("bundle", scanned.owner, f"compiler pass {scanned.name}")


def _package_dir(package: str | ModuleType) -> Path:
    if isinstance(package, ModuleType):
        location = package.__file__
    else:
        spec = importlib.util.find_spec(package)
        location = spec.origin if spec is not None else None
    if location is None:
        return Path.cwd()
    return Path(location).resolve().parent


def _load_bundles_module(package_name: str) -> Mapping[type[AnyBundle], Mapping[str, bool]]:
    """Import ``<package_name>.bundles`` and return its ``BUNDLES`` mapping.

    The convention mirrors Symfony's ``config/bundles.php``: the module is
    optional (a missing ``<package_name>.bundles`` yields an empty mapping),
    but a module that does exist must expose ``BUNDLES``.

    Raises:
        ResourceImportError: If ``<package_name>.bundles`` exists but a
            deeper import fails.
        BundleDefinitionError: If the module is present but lacks ``BUNDLES``,
            or if a listed class is not a decorated :class:`Bundle`.
    """
    module_name = f"{package_name}.bundles"
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as error:
        if error.name == module_name:
            return {}
        raise ResourceImportError(module_name) from error
    except ImportError as error:
        raise ResourceImportError(module_name) from error
    raw = getattr(module, "BUNDLES", None)
    if raw is None:
        raise BundleDefinitionError(module_name, "it does not define BUNDLES")
    if not isinstance(raw, Mapping):
        raise BundleDefinitionError(
            module_name, "BUNDLES must be a mapping of bundle class to activity flags"
        )
    result: dict[type[AnyBundle], Mapping[str, bool]] = {}
    for cls, flags in raw.items():  # pyright: ignore[reportUnknownVariableType]
        cls_obj = cast("object", cls)
        if not (isinstance(cls_obj, type) and issubclass(cls_obj, Bundle)):
            raise BundleDefinitionError(
                module_name, f"{cls_obj!r} listed in BUNDLES is not a Bundle subclass"
            )
        if not isinstance(flags, Mapping):
            raise BundleDefinitionError(
                module_name, f"activity flags for {cls_obj!r} must be a mapping"
            )
        result[cast("type[AnyBundle]", cls_obj)] = dict(cast("Mapping[str, bool]", flags))
    return result
