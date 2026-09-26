r"""The kernel: one line for the application, the whole build behind it.

``Kernel("app")`` does no work; it is a recipe. ``build()`` runs every step
below, in order, and returns a compiled container — each call independent of
the last, so tests and several kernels in one process never share a
container. The steps are:

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
from typing import TYPE_CHECKING, Literal, cast, final

from xtr_dependency_injection.builder.autoconfigurator import run_autoconfigurators
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
from xtr_dependency_injection.compiler._wireup_bridge import key_type
from xtr_dependency_injection.compiler.check_alias_validity_pass import validate_aliases_pass
from xtr_dependency_injection.compiler.decorator_service_pass import resolve_decorations_pass
from xtr_dependency_injection.compiler.priority_tagged_service import by_priority
from xtr_dependency_injection.compiler.remove_missing_dependencies_pass import (
    remove_if_missing_pass,
)
from xtr_dependency_injection.compiler.resolve_instanceof_conditionals_pass import (
    apply_autoconfigure_rules,
)
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
from xtr_dependency_injection.decorator.as_service import service_of
from xtr_dependency_injection.decorator.as_tagged_item import tagged_item_of
from xtr_dependency_injection.decorator.compiler_pass import compiler_pass_of
from xtr_dependency_injection.decorator.lifecycle import on_boot_of, on_shutdown_of
from xtr_dependency_injection.decorator.remove_if_missing import REMOVE_IF_MISSING_TAG
from xtr_dependency_injection.decorator.remove_if_missing import (
    markers_of as remove_if_missing_markers_of,
)
from xtr_dependency_injection.diagnostics import DefinitionReport
from xtr_dependency_injection.diagnostics.report import KernelReport, ReportBuilder
from xtr_dependency_injection.exception import (
    BundleDefinitionError,
    InvalidEnvironmentError,
    ResourceImportError,
)
from xtr_dependency_injection.exception._naming import key_name as _naming_key_name
from xtr_dependency_injection.exception._naming import qualified_name
from xtr_dependency_injection.scan.default_excludes import DEFAULT_EXCLUDES
from xtr_dependency_injection.scan.scanned_object import ScannedObject
from xtr_dependency_injection.scan.scanner import Scanner, ScanResult

from ._origins import origin_of as _origin_of
from ._origins import scanned_origin as _scanned_origin
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

    The kernel exposes ``kernel.name``, ``kernel.environment``, ``kernel.debug``,
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

    Each object becomes exactly one definition under its own type + qualifier;
    every ``@as_alias(Iface)`` records an alias
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
    (see :meth:`ContainerBuilder.register_attribute_for_autoconfiguration`);
    then the nominal rules registered by
    :meth:`ContainerBuilder.register_for_autoconfiguration` (subclass match)
    plus any ``@autoconfigure`` / ``@autoconfigure_tag`` markers on scanned
    classes apply to every non-kernel definition.
    """
    state.phase = "autoconfigure"

    def configurator_for(owner: str, candidate: ScannedObject) -> ServiceConfigurator:
        base = _origin_of(owner)
        origin = Origin(base.kind, base.name, f"via autoconfigure of {candidate.name}")
        return ServiceConfigurator(state, origin)

    run_autoconfigurators(state.autoconfigurators, candidates, configurator_for)
    apply_autoconfigure_rules(state, candidates)


def _run_compiler_passes(
    state: BuildState,
    bundles: Sequence[AnyBundle],
    scanned_passes: Sequence[ScannedObject],
    scanned_decorators: Sequence[ScannedObject],
) -> None:
    """Run every compiler pass, stage by stage.

    Collection order — bundle-as-compiler-pass, then application, then
    built-ins: for each active bundle in order — its ``process`` if the
    class overrides ``Bundle.process``, then whatever it added in ``build``
    via ``builder.add_compiler_pass``; then the application's scanned
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

    Collection order: bundles' own ``process`` (only when overridden),
    then the passes each bundle added via ``builder.add_compiler_pass``,
    then application ``@compiler_pass`` functions in scan order, then the
    built-in kernel passes.
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
        if _overrides(bundle, "process"):
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
    """Sort ``requests`` by stage, then priority descending, ties by collection order.

    Priority and collection order are handled by the shared :func:`by_priority`
    helper; the stage stays the primary key on top, applied as a stable sort
    over the priority-ordered result so within-stage order is preserved.
    """
    ranked = by_priority(requests, priority=lambda r: r.priority, order=lambda r: r.order)
    stage_order = {stage: index for index, stage in enumerate(PassStage)}
    return sorted(ranked, key=lambda r: stage_order[r.stage])


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
    """Return the ``scanned`` hooks by marker priority, highest first, then scan order."""
    ranked = by_priority(
        scanned,
        priority=lambda entry: cast("int", getattr(marker_of(entry.obj), "priority", 0)),
        order=lambda entry: entry.order,
    )
    return [cast("Callable[..., object]", entry.obj) for entry in ranked]


def _overrides(bundle: AnyBundle, method: str) -> bool:
    """Return whether ``bundle``'s class overrides ``Bundle.<method>`` rather than inheriting it."""
    return getattr(type(bundle), method) is not getattr(Bundle, method)


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

    The module is optional (a missing ``<package_name>.bundles`` yields an
    empty mapping), but a module that does exist must expose ``BUNDLES``.

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
