r"""The kernel: one line for the application, the whole build behind it.

``Kernel("app")`` does no work; it is a recipe. ``build()`` runs every step
below, in order, and returns a compiled container — each call independent of
the last, so tests and several kernels in one process never share a
container. The steps are:

1. environment — ``APP_ENV`` / ``APP_DEBUG`` or the arguments;
2. bundles — activation from ``bundles.py`` + ``@required_bundle``, in order;
3. early scan — the application's resources and the bundles';
4. prepare — every bundle overriding ``process`` becomes a compiler pass, every
   bundle's ``build(builder)`` runs, then the scanned ``@compiler_pass``
   classes are registered;
5. compiler passes — the merge pass (``prepend_extension``, configs,
   ``load_extension``, late scan, marked definitions), then every stage of the
   :class:`~xtr_dependency_injection.compiler.pass_config.PassConfig`;
6. compile — the wireup container.
"""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Final, cast, final

from xtr_dependency_injection.builder._origins import origin_of, scanned_origin
from xtr_dependency_injection.builder.container_builder import ContainerBuilder
from xtr_dependency_injection.builder.definition import Definition, Origin, ServiceKey
from xtr_dependency_injection.builder.service_configurator import BuildState
from xtr_dependency_injection.bundle import KERNEL_BUNDLE, NoConfig
from xtr_dependency_injection.bundle.bundle import AnyBundle, Bundle
from xtr_dependency_injection.bundle.bundle_resolver import resolve_bundles
from xtr_dependency_injection.compiler.merge_extension_configuration_pass import (
    MergeExtensionConfigurationPass,
)
from xtr_dependency_injection.compiler.pass_stage import PassStage
from xtr_dependency_injection.compiler.priority_tagged_service import by_priority
from xtr_dependency_injection.compiler.wireup_compiler import (
    Decoration,
    compile_container,
    emission_order,
    emit_injectables,
)
from xtr_dependency_injection.config.env_placeholder import ENV_PARAMETERS_ROOT, env_tokens
from xtr_dependency_injection.config.parameters import call_parameters, merge_parameters
from xtr_dependency_injection.decorator.compiler_pass import compiler_pass_of
from xtr_dependency_injection.decorator.lifecycle import on_boot_of, on_shutdown_of
from xtr_dependency_injection.diagnostics import DefinitionReport
from xtr_dependency_injection.diagnostics.report import KernelReport, ReportBuilder
from xtr_dependency_injection.exception import (
    BundleDefinitionError,
    InvalidEnvironmentError,
    InvalidEnvironmentVariableError,
    ResourceImportError,
)
from xtr_dependency_injection.exception._naming import key_name as _naming_key_name
from xtr_dependency_injection.exception._naming import qualified_name
from xtr_dependency_injection.scan.default_excludes import DEFAULT_EXCLUDES
from xtr_dependency_injection.scan.scanner import Scanner, ScanResult

from .booted_kernel import BootedKernel, call_injected
from .compiled_kernel import CompiledKernel
from .kernel_bundle import KernelBundle

if TYPE_CHECKING:
    from collections.abc import Awaitable, Sequence

    from xtr_dependency_injection.compiler.compiler_pass_interface import CompilerPassInterface
    from xtr_dependency_injection.scan.scanned_object import ScannedObject

__all__ = [
    "BUNDLE_PASS_PRIORITY",
    "Assembly",
    "Kernel",
    "Prepared",
    "assemble",
    "definition_reports",
    "prepare",
]

BUNDLE_PASS_PRIORITY: Final = -10000
"""Where a bundle overriding ``process`` runs: ``BEFORE_OPTIMIZATION``, after every other pass."""


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
        "_environ",
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
        environ: Mapping[str, str] | None = None,
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
            environ: Where ``APP_ENV``, ``APP_DEBUG`` and every ``env(...)``
                placeholder are read; ``None`` reads the live process
                environment. A test gives each kernel its own.
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
        self._environ = environ

    @property
    def name(self) -> str:
        """The application's name."""
        return self._name if self._name is not None else self._package_name.rsplit(".", 1)[-1]

    @property
    def environment(self) -> str:
        """The environment: the argument, else ``APP_ENV``, else ``"dev"``."""
        return (
            self._env
            if self._env is not None
            else self._environment_variables.get("APP_ENV", "dev")
        )

    @property
    def debug(self) -> bool:
        """Debug mode: the argument, else ``APP_DEBUG``, else true outside ``"prod"``.

        Raises:
            InvalidEnvironmentVariableError: If ``APP_DEBUG`` is neither
                ``1/true/yes/on`` nor ``0/false/no/off`` or empty.
        """
        if self._debug is not None:
            return self._debug
        value = self._environment_variables.get("APP_DEBUG")
        if value is None:
            return self.environment != "prod"
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off", ""}:
            return False
        raise InvalidEnvironmentVariableError("APP_DEBUG", bool, value)

    @property
    def _environment_variables(self) -> Mapping[str, str]:
        return self._environ if self._environ is not None else os.environ

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
            environ=self._environ,
        )

    def build(self) -> CompiledKernel:
        """Run steps 1 to 6 and return the compiled container, not yet booted."""
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
            environ=self._environ,
        )
        state = prepared.assembly.state
        parameters = merge_parameters(
            (origin.name if origin.kind == "app" else str(origin), values)
            for origin, values in state.parameters
        )
        # ``Autowire(env=...)`` injections read their placeholder from here, one
        # key per token, including those a hook or handler bound later adds.
        parameters[ENV_PARAMETERS_ROOT] = env_tokens()
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
    """What steps 3 to 5 produce: a frozen build state, ready to compile.

    Attributes:
        state: The definitions, parameters and requests of the build.
        decorations: Validated decorations per decorated key.
        on_boot: ``@on_boot`` hooks, in the order they run.
        on_shutdown: ``@on_shutdown`` hooks, in the order they run.
    """

    state: BuildState
    decorations: dict[ServiceKey, list[Decoration]]
    on_boot: list[Callable[..., object]]
    on_shutdown: list[Callable[..., object]]


def assemble(  # noqa: PLR0913 — steps 3 to 5 need all of these.
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
    environ: Mapping[str, str] | None = None,
) -> Assembly:
    """Run steps 3 to 5 for ``bundles``, recording into ``report``.

    Shared by :func:`prepare`, which computes ``active`` once for both the
    report and this call.
    """
    scanner = Scanner(env=environment, exclude=exclude)
    early = _early_scan(scanner, resources, bundles)
    state = BuildState(
        env=environment, debug=debug, bundles=tuple(active), configs={}, environ=environ
    )
    state.candidates.extend(early.services)
    state.scanned_decorators.extend(early.decorators)
    _register_kernel_parameters(
        state,
        name=name,
        environment=environment,
        debug=debug,
        project_dir=project_dir,
        bundles=bundles,
    )
    # Every parameter is known before the merge, which resolves configs against them.
    for scanned in early.parameters:
        values = call_parameters(cast("Callable[..., object]", scanned.obj))
        state.add_parameters(Origin("app", scanned.name), values)
    _prepare_container(state, bundles, early.compiler_passes)
    merge = MergeExtensionConfigurationPass(
        bundles=bundles,
        early=early,
        scanner=scanner,
        inactive=inactive_config_owners,
        report=report,
        given=given,
    )
    state.compiler.get_pass_config().set_merge_pass(merge)
    state.compiler.compile(state)
    late = merge.late
    report.modules.extend(scanner.modules)
    report.skipped.extend(scanner.skipped)
    return Assembly(
        state=state,
        decorations=state.decorations,
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
        assembly: What steps 3 to 5 produced.
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
    environ: Mapping[str, str] | None = None,
) -> Prepared:
    """Run steps 1's aftermath through 5, then emit: the pipeline both entry points share.

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
        environ=environ,
    )
    ordered = emission_order(assembly.state.store.entries(), assembly.state.forwards)
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


def _prepare_container(
    state: BuildState, bundles: Sequence[AnyBundle], scanned_passes: Sequence[ScannedObject]
) -> None:
    """Step 4: register the compiler passes, running every bundle's ``build`` in between.

    First every bundle overriding ``process`` is registered as a pass at
    ``BEFORE_OPTIMIZATION`` :data:`BUNDLE_PASS_PRIORITY`, in bundle order; then
    every bundle's ``build(builder)`` runs, which may add passes of its own;
    then every scanned ``@compiler_pass`` class is built with no arguments and
    registered, in scan order.
    """
    state.phase = "build"
    compiler = state.compiler
    for bundle in bundles:
        if _overrides(bundle, "process"):
            origin = origin_of(type(bundle).metadata().name)
            compiler.add_pass(
                bundle, PassStage.BEFORE_OPTIMIZATION, BUNDLE_PASS_PRIORITY, origin=origin
            )
    for bundle in bundles:
        bundle.build(ContainerBuilder(state, origin_of(type(bundle).metadata().name)))
    for scanned in scanned_passes:
        marker = compiler_pass_of(scanned.obj)
        if marker is None:  # pragma: no cover — the scanner queues only marked classes.
            continue
        pass_class = cast("type[CompilerPassInterface]", scanned.obj)
        origin = scanned_origin(scanned, "compiler pass")
        compiler.add_pass(pass_class(), marker.stage, marker.priority, origin=origin)


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
    state.add_parameters(
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
            arguments=tuple(f"{name}={value!r}" for name, value in definition.arguments.items()),
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
