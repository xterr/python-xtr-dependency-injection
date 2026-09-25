"""The kernel: one line for the application, the whole build behind it.

``Kernel("app")`` does no work; it is a recipe. ``build()`` runs every step
below, in order, and returns a compiled container — each call independent of
the last, so tests and several kernels in one process never share a
container. Each step is a separate function, so each can be tested alone:

1. environment — ``APP_ENV`` / ``APP_DEBUG`` or the arguments;
2. bundles — discovery, selection, requirements, environment, order;
3. early scan — the application's resources and the bundles';
4. configs — defaults, providers, prepends;
5. load — every bundle defines its services;
6. late scan — what bundles asked to scan while loading;
7. declared definitions — what is marked with wireup's ``@injectable``;
8. autoconfigure — bundles react to every scanned candidate;
9. process — bundles, then ``@compiler_pass`` functions;
10. finalize — resettable services and decorations; the builder freezes;
11. compile — the wireup container.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, cast, final

from xtr_dependency_injection.builder.autoconfigurator import run_autoconfigurators
from xtr_dependency_injection.builder.container_builder import ContainerBuilder
from xtr_dependency_injection.builder.definition import Definition, Origin, ServiceKey
from xtr_dependency_injection.builder.service_configurator import BuildState, ServiceConfigurator
from xtr_dependency_injection.bundle import NoConfig
from xtr_dependency_injection.compiler._wireup_bridge import declaration_of, provided_type
from xtr_dependency_injection.compiler.wireup_compiler import (
    Decoration,
    compile_container,
    emission_order,
    emit_injectables,
)
from xtr_dependency_injection.config.config_resolver import ResolvedConfigs, resolve_configs
from xtr_dependency_injection.config.env import env as read_env
from xtr_dependency_injection.config.parameters import call_parameters, merge_parameters
from xtr_dependency_injection.decorator.as_decorator import decorator_of, inner_parameter_of
from xtr_dependency_injection.decorator.compiler_pass import compiler_pass_of
from xtr_dependency_injection.decorator.lifecycle import on_boot_of, on_shutdown_of
from xtr_dependency_injection.diagnostics import DefinitionReport
from xtr_dependency_injection.diagnostics.report import ReportBuilder
from xtr_dependency_injection.discovery.bundle_discovery import DiscoveredBundle, discover_bundles
from xtr_dependency_injection.discovery.bundle_resolver import resolve_bundles
from xtr_dependency_injection.exception import InvalidEnvironmentError, UnknownServiceError
from xtr_dependency_injection.exception._naming import type_name
from xtr_dependency_injection.scan.default_excludes import DEFAULT_EXCLUDES
from xtr_dependency_injection.scan.scanned_object import ScannedObject
from xtr_dependency_injection.scan.scanner import Scanner, ScanResult

from .booted_kernel import BootedKernel, call_injected
from .compiled_kernel import CompiledKernel
from .kernel_bundle import KernelBundle

if TYPE_CHECKING:
    from collections.abc import Awaitable, Iterable, Mapping, Sequence

    from xtr_dependency_injection.bundle.bundle import AnyBundle

__all__ = ["Assembly", "Kernel", "assemble", "definition_reports"]


@final
class Kernel:
    """An application's kernel: which bundles, which resources, which environment.

    Constructing one stores its arguments and nothing else; ``build``,
    ``boot`` and ``run`` do the work, each time afresh.
    """

    __slots__ = (
        "_allowed_envs",
        "_bundle_envs",
        "_bundles",
        "_concurrent_scoped_access",
        "_debug",
        "_env",
        "_exclude",
        "_exclude_bundles",
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
        bundles: Sequence[AnyBundle] | None = None,
        exclude_bundles: Iterable[str] = (),
        bundle_envs: Mapping[str, Iterable[str]] | None = None,
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
            bundles: Exactly these bundles (plus what they require) instead
                of every discovered one.
            exclude_bundles: Names to leave out.
            bundle_envs: Per-name environments, overriding a bundle's own.
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
        self._bundles = tuple(bundles) if bundles is not None else None
        self._exclude_bundles = tuple(exclude_bundles)
        self._bundle_envs = (
            {key: tuple(value) for key, value in bundle_envs.items()} if bundle_envs else None
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
        """Return the same recipe for another environment."""
        return Kernel(
            self._package,
            env=env,
            debug=debug,
            name=self._name,
            bundles=self._bundles,
            exclude_bundles=self._exclude_bundles,
            bundle_envs=self._bundle_envs,
            resources=self._resources,
            exclude=self._exclude,
            allowed_envs=self._allowed_envs,
            concurrent_scoped_access=self._concurrent_scoped_access,
        )

    def build(self) -> CompiledKernel:
        """Run steps 1 to 11 and return the compiled container, not yet booted."""
        core = KernelBundle()
        environment, debug = _environment(self.environment, self.debug, self._allowed_envs)
        core.info.identify(
            name=self.name, environment=environment, debug=debug, project_dir=self.project_dir
        )
        report = ReportBuilder()
        discovered = discover_bundles()
        resolved = resolve_bundles(
            core=core,
            discovered=discovered,
            explicit=self._bundles,
            exclude=self._exclude_bundles,
            bundle_envs=self._bundle_envs,
            env=environment,
        )
        active = [type(bundle).metadata().name for bundle in resolved.bundles]
        core.info.activate(active)
        report.bundles.extend(resolved.reports)

        resources = self._resources if self._resources is not None else (self._package,)
        assembly = assemble(
            core=core,
            bundles=resolved.bundles,
            discovered=discovered,
            resources=resources,
            environment=environment,
            debug=debug,
            exclude=self._exclude,
            report=report,
        )
        return _compile(
            assembly,
            core,
            report,
            bundles=resolved.bundles,
            concurrent_scoped_access=self._concurrent_scoped_access,
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
            result = await call_injected(booted.container, main)
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
    core: KernelBundle,
    bundles: Sequence[AnyBundle],
    discovered: Sequence[DiscoveredBundle],
    resources: Sequence[str | ModuleType],
    environment: str,
    debug: bool,
    exclude: Sequence[str],
    report: ReportBuilder,
    given: Sequence[object] = (),
) -> Assembly:
    """Run steps 3 to 10 for ``bundles``, recording into ``report``.

    Shared by :meth:`Kernel.build` and standalone ``injectables()``, which
    differ only in how bundles are chosen and what becomes of the result.
    """
    active = [type(bundle).metadata().name for bundle in bundles]
    scanner = Scanner(env=environment, exclude=exclude)
    early = _early_scan(scanner, resources, bundles)
    configs = _configs(bundles, early, discovered, active, environment, given=given)
    report.configs.extend(configs.reports)
    report.skipped.extend(configs.skipped)
    core.provide(configs.values)

    state = BuildState(env=environment, debug=debug, bundles=tuple(active), configs=configs.values)
    _load(state, bundles, configs)
    late = _late_scan(scanner, state)
    _declared(state, [*early.declared, *late.declared])
    _autoconfigure(state, [*early.services, *late.services])
    _process(state, bundles, [*early.compiler_passes, *late.compiler_passes])
    decorations = _finalize(state, [*early.decorators, *late.decorators])
    report.modules.extend(scanner.modules)
    report.skipped.extend(scanner.skipped)
    return Assembly(
        state=state,
        decorations=decorations,
        parameter_providers=list(early.parameters),
        on_boot=_hooks([*early.on_boot, *late.on_boot], on_boot_of),
        on_shutdown=_hooks([*early.on_shutdown, *late.on_shutdown], on_shutdown_of),
    )


def _environment(environment: str, debug: bool, allowed: Sequence[str] | None) -> tuple[str, bool]:
    """Step 1: the environment and debug mode, checked against the allowed ones.

    Step 2, the bundles, is ``resolve_bundles`` itself.

    Raises:
        InvalidEnvironmentError: If the environment is not allowed.
    """
    if allowed is not None and environment not in allowed:
        raise InvalidEnvironmentError(environment, tuple(allowed))
    return environment, debug


def _early_scan(
    scanner: Scanner, resources: Sequence[str | ModuleType], bundles: Sequence[AnyBundle]
) -> ScanResult:
    """Step 3: the application's resources, then each active bundle's."""
    results = [scanner.scan(resources, owner=None)]
    for bundle in bundles:
        metadata = type(bundle).metadata()
        if metadata.resources:
            results.append(scanner.scan(metadata.resources, owner=metadata.name))
    return _merged(results)


def _configs(  # noqa: PLR0913 — the config step's inputs, each distinct.
    bundles: Sequence[AnyBundle],
    early: ScanResult,
    discovered: Sequence[DiscoveredBundle],
    active: Sequence[str],
    environment: str,
    *,
    given: Sequence[object] = (),
) -> ResolvedConfigs:
    """Step 4: every bundle's resolved config."""
    inactive = {
        entry.bundle.metadata().config: entry.name
        for entry in discovered
        if entry.bundle is not None
        and entry.name not in active
        and entry.bundle.metadata().config is not NoConfig
    }
    return resolve_configs(
        bundles=bundles,
        providers=early.configure,
        inactive=inactive,
        env=environment,
        given=given,
    )


def _load(state: BuildState, bundles: Sequence[AnyBundle], configs: ResolvedConfigs) -> None:
    """Step 5: every bundle defines its services, in order."""
    state.phase = "load"
    for bundle in bundles:
        name = type(bundle).metadata().name
        bundle.load(configs.values[name], ServiceConfigurator(state, _origin_of(name)))


def _late_scan(scanner: Scanner, state: BuildState) -> ScanResult:
    """Step 6: what bundles asked to scan while loading."""
    return _merged(
        [scanner.scan(resources, owner=owner, late=True) for owner, resources in state.late_scans]
    )


def _declared(state: BuildState, declared: Sequence[ScannedObject]) -> None:
    """Step 7: a definition for every object marked with wireup's ``@injectable``."""
    for scanned in declared:
        declaration = declaration_of(scanned.obj)
        if declaration is None:  # pragma: no cover — the scan only queues declared objects
            continue
        origin = (
            Origin("app", scanned.name)
            if scanned.owner is None
            else Origin("bundle", scanned.owner, f"declared by {scanned.name}")
        )
        state.store.add(
            Definition(
                key=(provided_type(declaration), declaration.qualifier),
                provider=scanned.obj,
                kind="declared",
                lifetime=declaration.lifetime,
                origin=origin,
            )
        )


def _autoconfigure(state: BuildState, candidates: Sequence[ScannedObject]) -> None:
    """Step 8: every autoconfigurator over every service candidate."""
    state.phase = "autoconfigure"

    def configurator_for(owner: str, candidate: ScannedObject) -> ServiceConfigurator:
        base = _origin_of(owner)
        origin = Origin(base.kind, base.name, f"via autoconfigure of {candidate.name}")
        return ServiceConfigurator(state, origin)

    run_autoconfigurators(state.autoconfigurators, candidates, configurator_for)


def _process(
    state: BuildState, bundles: Sequence[AnyBundle], passes: Sequence[ScannedObject]
) -> None:
    """Step 9: every bundle's ``process``, then the application's compiler passes."""
    state.phase = "process"
    for bundle in bundles:
        bundle.process(ContainerBuilder(state, _origin_of(type(bundle).metadata().name)))
    for scanned in _by_priority(passes, compiler_pass_of):
        run = cast("Callable[[ContainerBuilder], object]", scanned.obj)
        _ = run(ContainerBuilder(state, _scanned_origin(scanned)))


def _finalize(
    state: BuildState, decorators: Sequence[ScannedObject]
) -> dict[ServiceKey, list[Decoration]]:
    """Step 10: mark resettable services, validate decorations; the builder freezes.

    Raises:
        UnknownServiceError: If a resettable or decorated service is not
            defined.
        DecoratorSignatureError: If a decorator's ``Inner[...]`` is wrong.
    """
    for request in state.resettables:
        if state.store.get(request.key) is None:
            raise UnknownServiceError(request.key, "resettable")
        state.store.update(request.key, reset_method=request.method)
    requests: list[tuple[ServiceKey, int, int, object, str]] = [
        (r.key, r.priority, r.order, r.decorator, r.name) for r in state.decorations
    ]
    for offset, scanned in enumerate(decorators, start=len(requests)):
        marker = decorator_of(scanned.obj)
        if marker is not None:
            key = (marker.target, marker.qualifier)
            requests.append((key, marker.priority, offset, scanned.obj, scanned.name))
    decorations: dict[ServiceKey, list[Decoration]] = {}
    for key, _, _, decorator, name in sorted(requests, key=lambda r: (-r[1], r[2])):
        if state.store.get(key) is None:
            raise UnknownServiceError(key, "decorate")
        inner = inner_parameter_of(decorator, key[0])
        decorated = cast("type | Callable[..., object]", decorator)
        decorations.setdefault(key, []).append(Decoration(decorated, inner, name))
    state.phase = "frozen"
    return decorations


def _compile(
    assembly: Assembly,
    core: KernelBundle,
    report: ReportBuilder,
    *,
    bundles: Sequence[AnyBundle],
    concurrent_scoped_access: bool,
) -> CompiledKernel:
    """Step 11: merge parameters, emit, build the container, freeze the report."""
    state = assembly.state
    parameters = merge_parameters(
        [
            *state.parameters,
            *(
                (scanned.name, call_parameters(cast("Callable[..., object]", scanned.obj)))
                for scanned in assembly.parameter_providers
            ),
        ]
    )
    ordered = emission_order(state.store.definitions(), state.bundles)
    injectables = emit_injectables(ordered, assembly.decorations, core.resetter.track)
    container = compile_container(
        injectables,
        ordered,
        parameters=parameters,
        concurrent_scoped_access=concurrent_scoped_access,
    )
    report.definitions.extend(definition_reports(state, ordered, assembly.decorations))
    frozen = report.freeze()
    core.info.attach(frozen)
    return CompiledKernel(
        container,
        frozen,
        info=core.info,
        bundles=bundles,
        on_boot=assembly.on_boot,
        on_shutdown=assembly.on_shutdown,
    )


def definition_reports(
    state: BuildState,
    ordered: Sequence[Definition],
    decorations: Mapping[ServiceKey, Sequence[Decoration]],
) -> list[DefinitionReport]:
    """Return what the report says of each definition: origin, overrides, decorators."""
    return [
        DefinitionReport(
            key=definition.key,
            provider_qualname=type_name(
                type(definition.provider) if definition.kind == "instance" else definition.provider
            ),
            kind=definition.kind,
            lifetime=definition.lifetime,
            origin=definition.origin,
            overrides=state.store.overrides_of(definition.key),
            decorated_by=tuple(d.name for d in decorations.get(definition.key, ())),
        )
        for definition in ordered
    ]


def _merged(results: Sequence[ScanResult]) -> ScanResult:
    merged = ScanResult()
    for result in results:
        for field_name in ScanResult.__dataclass_fields__:
            into = cast("list[ScannedObject]", getattr(merged, field_name))
            into.extend(cast("list[ScannedObject]", getattr(result, field_name)))
    return merged


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
    return Origin("kernel", bundle) if bundle == "kernel" else Origin("bundle", bundle)


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
