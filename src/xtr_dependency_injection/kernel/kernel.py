r"""The kernel: one line for the application, the whole build behind it.

``Kernel(__package__)``, in the application package's ``kernel.py``, does no
work; it is a recipe. ``build()`` runs every step
below, in order, and returns a compiled container — each call independent of
the last, so tests and several kernels in one process never share a
container. The steps are:

1. environment — ``APP_ENV`` / ``APP_DEBUG`` or the arguments;
2. bundles — activation from ``config/bundles.py`` + ``@required_bundle``, in order;
3. early scan — the application's resources, the current environment's
   folders last, then the bundles';
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
import importlib.util
import logging
import os
import warnings
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
from xtr_dependency_injection.bundle._absent_bundle import AbsentBundle
from xtr_dependency_injection.bundle.bundle import AnyBundle, Bundle
from xtr_dependency_injection.bundle.bundle_resolver import ListedBundles, resolve_bundles
from xtr_dependency_injection.compiler.merge_extension_configuration_pass import (
    MergeExtensionConfigurationPass,
)
from xtr_dependency_injection.compiler.pass_stage import BUNDLE_PASS_PRIORITY, PassStage
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
from xtr_dependency_injection.diagnostics.report import (
    BundleReport,
    KernelReport,
    ReportBuilder,
    SetAsideReport,
)
from xtr_dependency_injection.exception import (
    InvalidArgumentError,
    InvalidArgumentTypeError,
    InvalidEnvironmentError,
    InvalidEnvironmentVariableError,
)
from xtr_dependency_injection.exception._naming import key_name as _naming_key_name
from xtr_dependency_injection.exception._naming import qualified_name
from xtr_dependency_injection.runtime._unit_scope import building_singleton
from xtr_dependency_injection.runtime.service_locator_injectables import (
    service_locator_injectables,
)
from xtr_dependency_injection.scan.default_excludes import DEFAULT_EXCLUDES
from xtr_dependency_injection.scan.scanner import Scanner, ScanResult

from ._bundle_list import load_bundle_list
from .booted_kernel import BootedKernel, call_injected
from .cache_dir import cache_dir
from .compiled_kernel import CompiledKernel
from .kernel_bundle import KernelBundle
from .share_dir import share_dir

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

_DEBUG_ENVS: Final = frozenset({"dev", "test"})
# The two environments the kernel itself names — "dev" is its own default
# environment, "test" is the convention every scaffold declares; anything else
# must ask for debug explicitly.

_DEBUG_DEFAULT_WARNED: set[str] = set()
# Module-level because the property may be read more than once and the kernel
# has no private environ to mark: this keeps the migration warning to one per
# environment name, per process.

_LOGGER: Final = logging.getLogger("xtr_dependency_injection")


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
        "_default_excludes",
        "_env",
        "_environ",
        "_exclude",
        "_name",
        "_package",
        "_resources",
    )

    def __init__(  # noqa: PLR0913 — each argument is a separate, optional decision.
        self,
        package: str | ModuleType | None,
        /,
        *,
        env: str | None = None,
        debug: bool | None = None,
        name: str | None = None,
        bundles: Mapping[type[AnyBundle], Mapping[str, bool]] | None = None,
        resources: Sequence[str] | None = None,
        exclude: Sequence[str] = (),
        default_excludes: bool = True,
        allowed_envs: Sequence[str] | None = None,
        concurrent_scoped_access: bool = True,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        """Store the kernel's recipe.

        Args:
            package: The application package, scanned recursively: its dotted
                name or the module. ``Kernel(__package__)`` in the package's
                own ``kernel.py`` names it once, where it cannot drift.
            env: The environment; default ``APP_ENV``, else ``"dev"``.
            debug: Debug mode; default ``APP_DEBUG``, else true for ``"dev"``
                and ``"test"``.
            name: The application's name; default the package's last
                component.
            bundles: The bundle classes the application lists, mapped to
                their per-environment activity flags (``{"all": True}`` or
                ``{"dev": True}``). When ``None`` the kernel imports
                ``<package>.config.bundles`` — or ``<package>.bundles`` when
                that is absent — and reads its ``BUNDLES`` mapping. A class
                that list imports from a package that is not installed is
                stood in for, and reported disabled where its flags leave it
                inactive.
            resources: What to scan instead of ``package``.
            exclude: ``fnmatch`` patterns of modules never scanned, added to
                ``DEFAULT_EXCLUDES``. A pattern starting with ``.`` is
                relative to the application package — ``".scripts"`` is
                ``"<package>.scripts"`` — whatever ``resources`` names.
            default_excludes: Whether ``DEFAULT_EXCLUDES`` applies; false
                leaves ``exclude`` alone.
            allowed_envs: The only environments the kernel accepts, and the
                only names a folder under ``config/packages/`` or
                ``config/routes/`` may take.
            concurrent_scoped_access: Whether a scoped service is built under
                a lock, so tasks of one unit of work asking for it together
                get the one instance; ``False`` drops the lock, for a unit
                only ever used by one task at a time.
            environ: Where ``APP_ENV``, ``APP_DEBUG`` and every ``env(...)``
                placeholder are read; ``None`` reads the live process
                environment. A test gives each kernel its own.

        Raises:
            InvalidArgumentError: If ``package`` is ``None`` or empty — what
                ``__package__`` is in a script run on its own, outside any
                package.
        """
        if package is None or package == "":
            msg = (
                f"Kernel was given {package!r} as the application package; put kernel.py "
                "inside the application package and build the kernel with Kernel(__package__)"
            )
            raise InvalidArgumentError(msg)
        self._package: str | ModuleType = package
        self._env = env
        self._debug = debug
        self._name = name
        self._bundles: Mapping[type[AnyBundle], Mapping[str, bool]] | None = (
            dict(bundles) if bundles is not None else None
        )
        self._resources = tuple(resources) if resources is not None else None
        self._exclude = tuple(exclude)
        self._default_excludes = default_excludes
        self._allowed_envs = tuple(allowed_envs) if allowed_envs is not None else None
        self._concurrent_scoped_access = concurrent_scoped_access
        self._environ = environ

    @property
    def name(self) -> str:
        """The application's name."""
        return self._name if self._name is not None else self.package.rsplit(".", 1)[-1]

    @property
    def package(self) -> str:
        """The application package, dotted."""
        return self._package if isinstance(self._package, str) else self._package.__name__

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
        """Debug mode: the argument, else ``APP_DEBUG``, else true for ``"dev"`` and ``"test"``.

        Any other environment fails closed — debug is off — so a
        security-relevant flag never defaults to on for a name the kernel does
        not know. ``"prod"`` is off silently; an environment outside
        ``"dev"``, ``"test"`` and ``"prod"`` warns once per process, saying
        how to ask for debug explicitly.

        Raises:
            InvalidEnvironmentVariableError: If ``APP_DEBUG`` is neither
                ``1/true/yes/on`` nor ``0/false/no/off`` or empty.
        """
        if self._debug is not None:
            return self._debug
        value = self._environment_variables.get("APP_DEBUG")
        if value is None:
            environment = self.environment
            if environment in _DEBUG_ENVS:
                return True
            if environment not in _DEBUG_DEFAULT_WARNED and environment != "prod":
                _DEBUG_DEFAULT_WARNED.add(environment)
                msg = (
                    f"Debug mode defaulted to off: environment {environment!r} is not one the "
                    "kernel names ('dev' or 'test'); set APP_DEBUG=1 or pass debug= to the "
                    "Kernel to turn it on."
                )
                warnings.warn(msg, RuntimeWarning, stacklevel=2)
            return False
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
            default_excludes=self._default_excludes,
            allowed_envs=self._allowed_envs,
            concurrent_scoped_access=self._concurrent_scoped_access,
            environ=self._environ,
        )

    def build(self) -> CompiledKernel:
        """Run steps 1 to 6 and return the compiled container, not yet booted."""
        environment, debug = self.environment, self.debug
        _check_environment(environment, self._allowed_envs)
        listed = self._bundles if self._bundles is not None else load_bundle_list(self.package)
        prepared = prepare(
            name=self.name,
            package=self.package,
            environment=environment,
            debug=debug,
            project_dir=self.project_dir,
            listed=listed,
            resources=self._resources if self._resources is not None else (self._package,),
            exclude=self._scan_excludes,
            allowed_envs=self._allowed_envs,
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
            raise InvalidArgumentTypeError(msg)
        return result

    @property
    def _scan_excludes(self) -> tuple[str, ...]:
        """The patterns the scan leaves out: the defaults, then ``exclude`` made absolute."""
        defaults = DEFAULT_EXCLUDES if self._default_excludes else ()
        given = (
            f"{self.package}{pattern}" if pattern.startswith(".") else pattern
            for pattern in self._exclude
        )
        return (*defaults, *given)


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
    package: str,
    bundles: Sequence[AnyBundle],
    active: Sequence[str],
    inactive_config_owners: Mapping[type, str],
    resources: Sequence[str | ModuleType],
    environment: str,
    debug: bool,
    project_dir: Path,
    exclude: Sequence[str],
    report: ReportBuilder,
    allowed_envs: Sequence[str] | None = None,
    given: Sequence[object] = (),
    environ: Mapping[str, str] | None = None,
    inactive_packages: Sequence[str] = (),
    application_exclude: Sequence[str] = (),
    sets_aside: bool = False,
) -> Assembly:
    """Run steps 3 to 5 for ``bundles``, recording into ``report``.

    Shared by :func:`prepare`, which computes ``active`` once for both the
    report and this call; ``sets_aside`` — whether a listed bundle is not
    active — with which the application scan sets aside a module needing a
    package that is not installed; ``inactive_packages`` — the packages of
    those bundles — which make such a module expected; and
    ``application_exclude`` — the resources of those bundles — which the
    application scan leaves out.
    """
    scanner = Scanner(
        env=environment,
        exclude=exclude,
        package=package,
        allowed_envs=allowed_envs,
        inactive_packages=inactive_packages,
        application_exclude=application_exclude,
        sets_aside=sets_aside,
    )
    early = _early_scan(scanner, resources, bundles)
    state = BuildState(
        env=environment, debug=debug, bundles=tuple(active), configs={}, environ=environ
    )
    state.candidates.extend(early.services)
    state.scanned_decorators.extend(early.decorators)
    state.set_aside.extend(early.set_aside)
    state.set_aside_modules.update((entry.module, entry) for entry in scanner.set_aside)
    _register_kernel_parameters(
        state,
        name=name,
        package=package,
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
    report.set_aside.extend(scanner.set_aside)
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
    package: str,
    environment: str,
    debug: bool,
    project_dir: Path,
    listed: ListedBundles,
    resources: Sequence[str | ModuleType],
    exclude: Sequence[str],
    allowed_envs: Sequence[str] | None = None,
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
    core.info.identify(
        name=name, package=package, environment=environment, debug=debug, project_dir=project_dir
    )
    report = ReportBuilder()
    resolved = resolve_bundles(core=core, listed=listed, env=environment)
    active = [type(bundle).metadata().name for bundle in resolved.bundles]
    core.info.activate(active)
    report.bundles.extend(resolved.reports)
    inactive_config_owners = _inactive_config_owners(listed, active)
    inactive_listed = _inactive_listed(resolved.reports)
    assembly = assemble(
        name=name,
        package=package,
        bundles=resolved.bundles,
        active=active,
        inactive_config_owners=inactive_config_owners,
        resources=resources,
        environment=environment,
        debug=debug,
        project_dir=project_dir,
        exclude=exclude,
        report=report,
        allowed_envs=allowed_envs,
        given=given,
        environ=environ,
        inactive_packages=_inactive_packages(inactive_listed, listed, package),
        application_exclude=_inactive_resources(listed, active),
        sets_aside=bool(inactive_listed),
    )
    _log_set_aside(report.set_aside)
    ordered = emission_order(assembly.state.store.entries(), assembly.state.forwards)
    injectables = emit_injectables(
        ordered,
        assembly.decorations,
        core.resetter.track,
        singleton_guard=building_singleton if debug else None,
    )
    injectables.extend(service_locator_injectables(ordered))
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
    """Step 3: the application's resources, then each active bundle's.

    The application's scan leaves out the resources of every listed bundle
    that is not active (see :func:`_inactive_resources`). Where a bundle is
    active, what the application scan already found is never found twice.
    """
    merged = scanner.scan(resources, owner=None)
    for bundle in bundles:
        metadata = type(bundle).metadata()
        if metadata.resources:
            merged.extend(scanner.scan(metadata.resources, owner=metadata.name))
    return merged


def _inactive_resources(listed: ListedBundles, active: Sequence[str]) -> tuple[str, ...]:
    """Return the resources of each listed bundle not active, for the application scan to skip.

    A bundle active only for development keeps the modules it declares — and
    whatever they import — out of every other environment: a resource inside
    the application package is not imported by the application's own scan
    where its bundle does not run. Where it runs, the application scan walks
    it as ever. A bundle whose package is not installed declares nothing.
    """
    names = dict.fromkeys(
        resource
        for entry in listed
        if not isinstance(entry, AbsentBundle) and entry.metadata().name not in active
        for resource in entry.metadata().resources
    )
    return tuple(names)


def _inactive_listed(reports: Sequence[BundleReport]) -> list[BundleReport]:
    """Return the report of each bundle the application lists that is not active here."""
    return [report for report in reports if report.source == "listed" and report.state != "active"]


def _inactive_packages(
    reports: Sequence[BundleReport], listed: ListedBundles, application: str
) -> tuple[str, ...]:
    """Return the package of each listed bundle that is not active, sorted.

    The bundle list says which bundles each environment runs. Where one does
    not run — disabled here, or not installed — what only it uses, its own
    package or a development library its environments need, may be missing
    from the installation, so the application scan sets aside a module needing
    what is not installed. Where every listed bundle runs, nothing is expected
    to be missing, and the tuple is empty.

    A bundle's package is its top-level one — that of its distribution — or,
    sharing a namespace with the application, the first package of its path
    the application is not in. A bundle the application defines itself owns
    its own module and the resources it declares — never the whole
    application, nor a folder other bundles share.
    """
    classes = {
        qualified_name(entry): entry for entry in listed if not isinstance(entry, AbsentBundle)
    }
    packages: set[str] = set()
    for report in _inactive_listed(reports):
        module = report.qualname.partition(":")[0]
        if not application or (module != application and not module.startswith(f"{application}.")):
            package = _own_package(module, application)
            # A bundle in a namespace the application shares: never the application's own path.
            if not _holds(package, application):
                packages.add(package)
            continue
        if module != application:
            packages.add(module)
        # A bundle of the application is installed with it: its class is in the list.
        packages.update(classes[report.qualname].metadata().resources)
    return tuple(sorted(packages))


def _own_package(module: str, application: str) -> str:
    """Return the first package of ``module``'s path that holds no part of ``application``."""
    parts = module.split(".")
    package = parts[0]
    for part in parts[1:]:
        if not _holds(package, application):
            break
        package = f"{package}.{part}"
    return package


def _holds(package: str, application: str) -> bool:
    """Whether ``package`` is ``application``, or a package ``application`` lies in."""
    return bool(application) and (application == package or application.startswith(f"{package}."))


def _log_set_aside(set_aside: Sequence[SetAsideReport]) -> None:
    """Say, once per build, what the scan set aside — and warn of what no inactive bundle explains.

    A module that needs, or reaches, the package of a listed bundle that is
    not active is set aside as expected. One that does not may be just as
    expected — a helper using a development library alone — or need a
    dependency missing from the installation, or carry a mistyped import:
    the warning names it, and an environment where every listed bundle runs
    refuses it outright.
    """
    if not set_aside:
        return
    needed = sorted({package for entry in set_aside for package in entry.missing})
    _LOGGER.info(
        (
            "Set aside %d module(s) needing packages that are not installed (%s); nothing they "
            "define is registered. The kernel report's scan section lists them."
        ),
        len(set_aside),
        ", ".join(needed),
    )
    unexplained = [entry for entry in set_aside if not entry.expected]
    if unexplained:
        modules = ", ".join(
            f"{entry.module} (needs {', '.join(entry.missing)})" for entry in unexplained
        )
        _LOGGER.warning(
            (
                "Set aside %s, reaching no package of a listed bundle inactive here: expected "
                "of a helper using a development library alone, but a dependency missing "
                "from this installation, or a mistyped import, looks the same."
            ),
            modules,
        )


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


def _register_kernel_parameters(  # noqa: PLR0913 — the kernel identity is a fixed 6-field shape.
    state: BuildState,
    *,
    name: str,
    package: str,
    environment: str,
    debug: bool,
    project_dir: Path,
    bundles: Sequence[AnyBundle],
) -> None:
    """Register the ``kernel.*`` parameters into ``state`` before any bundle's ``build`` runs.

    The kernel exposes ``kernel.name``, ``kernel.package``, ``kernel.environment``,
    ``kernel.debug``, ``kernel.project_dir``, ``kernel.share_dir``,
    ``kernel.cache_dir``, ``kernel.build_dir`` and ``kernel.bundles``
    (name → class) from the very beginning of the container build; every
    bundle's hook may read them. ``kernel.build_dir``, where what is only ever
    read goes, is the cache directory itself.
    """
    bundles_map = {type(bundle).metadata().name: qualified_name(type(bundle)) for bundle in bundles}
    environment_cache = str(cache_dir(project_dir, environment))
    state.add_parameters(
        Origin("kernel", KERNEL_BUNDLE),
        {
            KERNEL_BUNDLE: {
                "name": name,
                "package": package,
                "environment": environment,
                "debug": debug,
                "project_dir": str(project_dir),
                "share_dir": str(share_dir(project_dir)),
                "cache_dir": environment_cache,
                "build_dir": environment_cache,
                "bundles": bundles_map,
            }
        },
    )


def _inactive_config_owners(
    listed: ListedBundles,
    active: Sequence[str],
) -> Mapping[type, str]:
    """Return a mapping ``config_type -> bundle name`` for listed but env-disabled bundles."""
    result: dict[type, str] = {}
    for bundle_type in listed:
        if isinstance(bundle_type, AbsentBundle):
            # Its package is not installed, so nothing can configure it.
            continue
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
        found = importlib.util.find_spec(package)
        location = found.origin if found is not None else None
    if location is None:
        return Path.cwd()
    return Path(location).resolve().parent
