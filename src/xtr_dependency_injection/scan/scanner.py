"""Importing resources and sorting what they define.

The scan imports a package's modules, sorted by name, and looks only at the
functions and classes each module *defines* — an imported name belongs to the
module that defined it. Every object found goes to exactly one place: a
queue for its marker (``@configure``, ``@on_boot``…), or the service
candidates autoconfiguration looks at. An object excluded, or left out of the
environment, goes nowhere; the latter is reported.

A direct subpackage of the application's ``config.packages`` or
``config.routes`` is an *environment folder*, named after an environment. It
is imported only in that environment, after everything else the scan walks,
so what it configures or routes comes after the common modules; another
environment's folder is never imported at all.

Where a bundle the application lists is not active — disabled for the
environment, or not installed at all — what only that bundle's environments
use may be missing from the installation too: a development library, the
bundle's own package. Application modules import them all the same: data to
seed a database with, say. There, and only there, the application scan *sets
aside* a module that fails to import because a package it needs is not
installed, rather than failing (see
:mod:`~xtr_dependency_injection.scan._inspection` for how):

- the module's code is run once more, in a namespace of its own, with each
  such package stood in for where its import statements ask for it, to learn
  what it defines;
- nothing it defines is registered, and it is not loaded once the scan ends,
  so a later import fails as it would have;
- anything it defines that would be used — a marker of this package on it,
  or a bundle's autoconfiguration claiming it — fails the build with
  :class:`~xtr_dependency_injection.exception.SetAsideModuleUsedError`.

Where every listed bundle is active, every import that fails is a
:class:`ResourceImportError`, as is, everywhere, a module missing from a
package that is installed, the application's own included.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from types import ModuleType
from typing import TYPE_CHECKING, Final, cast, final

from xtr_dependency_injection.config.configure import configure_of
from xtr_dependency_injection.config.parameters import is_parameters
from xtr_dependency_injection.decorator.as_alias import aliases_of
from xtr_dependency_injection.decorator.as_decorator import decorator_of
from xtr_dependency_injection.decorator.as_service import service_of
from xtr_dependency_injection.decorator.as_tagged_item import tagged_item_of
from xtr_dependency_injection.decorator.autoconfigure import autoconfigure_of, autoconfigure_tags_of
from xtr_dependency_injection.decorator.compiler_pass import compiler_pass_of
from xtr_dependency_injection.decorator.exclude import is_excluded
from xtr_dependency_injection.decorator.lifecycle import on_boot_of, on_shutdown_of
from xtr_dependency_injection.decorator.when import matches_env, when_envs_of, when_not_envs_of
from xtr_dependency_injection.exception import (
    ConfigProviderError,
    ResourceImportError,
    SetAsideModuleUsedError,
    UnknownEnvironmentFolderError,
)
from xtr_dependency_injection.exception._naming import qualified_name

from ._inspection import LOCK, Inspection
from ._stand_ins import unwrapped
from .scanned_object import ScannedObject

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Iterator, Sequence

    from xtr_dependency_injection.diagnostics.report import SetAsideReport

    from ._inspection import SetAsideModule

__all__ = ["ScanResult", "Scanner"]

_QUEUES: Final[tuple[tuple[str, str, Callable[[object], object]], ...]] = (
    ("@configure", "configure", configure_of),
    ("@parameters", "parameters", lambda obj: is_parameters(obj) or None),
    ("@compiler_pass", "compiler_passes", compiler_pass_of),
    ("@on_boot", "on_boot", on_boot_of),
    ("@on_shutdown", "on_shutdown", on_shutdown_of),
    ("@as_decorator", "decorators", decorator_of),
)
_EARLY_ONLY: Final = frozenset({"@configure", "@parameters", "@compiler_pass"})
_ENVIRONMENT_FOLDER_PARENTS: Final = ("config.packages", "config.routes")
"""Where, inside the application package, a subpackage is an environment folder."""


@dataclass(slots=True)
class ScanResult:
    """What one scan found, sorted by where each object goes.

    Attributes:
        configure: ``@configure`` providers.
        parameters: ``@parameters`` providers.
        compiler_passes: ``@compiler_pass`` classes.
        on_boot: ``@on_boot`` hooks.
        on_shutdown: ``@on_shutdown`` hooks.
        decorators: ``@as_decorator`` classes and factories.
        marked: Objects carrying ``@as_service`` or ``@as_alias``.
        services: Every service candidate — the marked ones included — for
            autoconfiguration.
        set_aside: Every function and class of a set-aside module, which
            nothing may use.
    """

    configure: list[ScannedObject] = field(default_factory=list)
    parameters: list[ScannedObject] = field(default_factory=list)
    compiler_passes: list[ScannedObject] = field(default_factory=list)
    on_boot: list[ScannedObject] = field(default_factory=list)
    on_shutdown: list[ScannedObject] = field(default_factory=list)
    decorators: list[ScannedObject] = field(default_factory=list)
    marked: list[ScannedObject] = field(default_factory=list)
    services: list[ScannedObject] = field(default_factory=list)
    set_aside: list[ScannedObject] = field(default_factory=list)

    def extend(self, other: ScanResult) -> None:
        """Append everything ``other`` found to this result, queue by queue, in order."""
        for field_name in ScanResult.__dataclass_fields__:
            into = cast("list[ScannedObject]", getattr(self, field_name))
            into.extend(cast("list[ScannedObject]", getattr(other, field_name)))


@final
class Scanner:
    """Scans resources for one build: early, then late, never finding an object twice."""

    __slots__ = (
        "_allowed_envs",
        "_application_exclude",
        "_env",
        "_environment_parents",
        "_exclude",
        "_held",
        "_inactive",
        "_inspection",
        "_module_names",
        "_order",
        "_package",
        "_scanning_application",
        "_seen",
        "_sets_aside",
        "modules",
        "set_aside",
        "skipped",
    )

    def __init__(  # noqa: PLR0913 — each argument is a separate decision of the build
        self,
        *,
        env: str,
        exclude: Sequence[str],
        package: str = "",
        allowed_envs: Sequence[str] | None = None,
        inactive_packages: Collection[str] = (),
        application_exclude: Sequence[str] = (),
        sets_aside: bool | None = None,
    ) -> None:
        """Scan for ``env``, leaving out modules matching the ``exclude`` patterns.

        Args:
            env: The environment the build is for.
            exclude: ``fnmatch`` patterns of module names never imported.
            package: The application package, whose ``config.packages`` and
                ``config.routes`` hold the environment folders; empty for
                none.
            allowed_envs: The environments an environment folder may be
                named after; ``None`` takes every folder name as one.
            inactive_packages: The packages of the bundles the application
                lists and that are not active here: a module set aside that
                needs or reaches one is expected.
            application_exclude: Module names the application's own scan
                leaves out — what a listed bundle not active here declares —
                while a bundle's scan still walks them.
            sets_aside: Whether a bundle the application lists is not active
                here: then the application scan sets aside a module needing
                a package that is not installed; else every failed import
                fails the scan. ``None`` takes it from ``inactive_packages``.
        """
        self._env = env
        self._exclude = tuple(exclude)
        self._application_exclude = frozenset(application_exclude)
        self._scanning_application = False
        self._package = package
        self._environment_parents = (
            frozenset(f"{package}.{parent}" for parent in _ENVIRONMENT_FOLDER_PARENTS)
            if package
            else frozenset[str]()
        )
        self._allowed_envs = tuple(allowed_envs) if allowed_envs is not None else None
        self._inactive = frozenset(inactive_packages)
        self._sets_aside = bool(self._inactive) if sets_aside is None else sets_aside
        self._seen: set[int] = set()
        # What set-aside modules define is dropped with them; their ids in _seen must stay theirs:
        # every object whose id enters _seen is held for the scanner's life.
        self._held: list[object] = []
        self._order = 0
        self.modules: list[str] = []
        self._module_names: set[str] = set()
        self.skipped: list[tuple[str, str]] = []
        self.set_aside: list[SetAsideReport] = []
        self._inspection: Inspection | None = None

    def scan(
        self, resources: Sequence[str | ModuleType], *, owner: str | None, late: bool = False
    ) -> ScanResult:
        """Import ``resources`` and sort what they define.

        The application's resources (``owner`` ``None``), scanned where a
        listed bundle is not active, set aside a module needing a package
        that is not installed; see the module documentation.

        Args:
            resources: Packages (walked recursively) or plain modules.
            owner: The bundle the resources belong to; ``None`` for the
                application.
            late: Whether this scan runs after configs are resolved, as one
                a bundle requested while loading does.

        Raises:
            ResourceImportError: If a module fails to import.
            UnknownEnvironmentFolderError: If an environment folder is not
                named after an allowed environment.
            ConfigProviderError: If an object carries two queue markers, or a
                late scan finds a ``@configure``, ``@parameters`` or
                ``@compiler_pass`` — each is needed before bundles load.
            SetAsideModuleUsedError: If a set-aside module defines an object
                carrying a marker of this package.
        """
        result = ScanResult()
        self._scanning_application = owner is None
        try:
            if owner is not None or not self._sets_aside:
                self._sort(resources, owner, result, late=late)
                return result
            self._inspecting_sort(resources, result, late=late)
        finally:
            self._scanning_application = False
        return result

    def _inspecting_sort(
        self, resources: Sequence[str | ModuleType], result: ScanResult, *, late: bool
    ) -> None:
        application = tuple(
            name
            for name in (
                self._package,
                *(r.__name__ if isinstance(r, ModuleType) else r for r in resources),
            )
            if name
        )
        with LOCK, Inspection(application, self._inactive) as inspection:
            self._inspection = inspection
            try:
                self._sort(resources, None, result, late=late)
                # Only a scan that ends says what it set aside: one failing has half of it.
                self.set_aside.extend(inspection.reports())
            finally:
                self._inspection = None

    def _sort(
        self,
        resources: Sequence[str | ModuleType],
        owner: str | None,
        result: ScanResult,
        *,
        late: bool,
    ) -> None:
        for module, in_environment_folder in self._modules(resources):
            set_aside = self._set_aside_entry(module.__name__)
            candidates = self._candidates(
                module, owner, in_environment_folder=in_environment_folder
            )
            for held, scanned in candidates:
                if set_aside is None:
                    self._classify(scanned, result, late=late)
                else:
                    self._put_aside(scanned, held, module.__name__, set_aside, result)

    def _set_aside_entry(self, name: str) -> SetAsideModule | None:
        inspection = self._inspection
        return inspection.set_aside.get(name) if inspection is not None else None

    def _modules(self, resources: Sequence[str | ModuleType]) -> Iterator[tuple[ModuleType, bool]]:
        """Yield each module, and whether it lies in an environment folder — those come last."""
        folders: list[str] = []
        for resource in resources:
            root = resource if isinstance(resource, ModuleType) else self._import(resource)
            yield from ((module, False) for module in self._walk(root, folders))
        for folder in folders:
            yield from ((module, True) for module in self._walk(self._import(folder), folders))

    def _walk(self, module: ModuleType, folders: list[str]) -> Iterator[ModuleType]:
        """Yield ``module`` and what it holds; queue this environment's folders into ``folders``."""
        name = module.__name__
        if name not in self._module_names and self._set_aside_entry(name) is None:
            self._module_names.add(name)
            self.modules.append(name)
        yield module
        # Read where the import system sets it: a module ``__getattr__`` may answer any name.
        path = cast("list[str] | None", vars(module).get("__path__"))
        if path is None:
            return
        holds_folders = name in self._environment_parents
        children = sorted(pkgutil.iter_modules(path, f"{name}."), key=lambda m: m.name)
        for child in children:
            if self._excluded(child.name):
                continue
            if holds_folders and child.ispkg:
                if self._is_current_environment(child.name):
                    folders.append(child.name)
                continue
            yield from self._walk(self._import(child.name), folders)

    def _import(self, name: str) -> ModuleType:
        inspection = self._inspection
        return inspection.import_module(name) if inspection is not None else _import(name)

    def _excluded(self, name: str) -> bool:
        if self._scanning_application and name in self._application_exclude:
            return True
        return any(fnmatchcase(name, pattern) for pattern in self._exclude)

    def _is_current_environment(self, folder: str) -> bool:
        """Return whether ``folder`` is the build's environment folder, reporting it if not.

        Raises:
            UnknownEnvironmentFolderError: If its name is not an allowed environment.
        """
        environment = folder.rsplit(".", 1)[-1]
        if self._allowed_envs is not None and environment not in self._allowed_envs:
            raise UnknownEnvironmentFolderError(folder, self._allowed_envs)
        if environment == self._env:
            return True
        self.skipped.append((folder, f"environment folder for {environment!r}, not {self._env!r}"))
        return False

    def _candidates(
        self, module: ModuleType, owner: str | None, *, in_environment_folder: bool
    ) -> Iterator[tuple[object, ScannedObject]]:
        """Yield each function and class ``module`` defines, with the value the module holds.

        A set-aside module may hold what a stand-in decorator remembers, in
        its object's place: the object is what it defines, and the value
        held what a marker over that decorator was put on.
        """
        values = cast("list[object]", list(vars(module).values()))
        for value in values:
            obj = unwrapped(value)
            if not (inspect.isfunction(obj) or inspect.isclass(obj)):
                continue
            if getattr(obj, "__module__", None) != module.__name__ or id(obj) in self._seen:
                continue
            self._seen.add(id(obj))
            self._held.append(obj)
            self._order += 1
            yield (
                value,
                ScannedObject(
                    obj,
                    qualified_name(obj),
                    owner,
                    self._order,
                    in_environment_folder=in_environment_folder,
                ),
            )

    def _classify(self, scanned: ScannedObject, result: ScanResult, *, late: bool) -> None:
        obj = scanned.obj
        if is_excluded(obj):
            return
        if not matches_env(obj, self._env):
            self.skipped.append((scanned.name, _env_reason(obj, self._env)))
            return
        matched = [(label, field) for label, field, read in _QUEUES if read(obj) is not None]
        if len(matched) > 1:
            labels = " and ".join(label for label, _ in matched)
            raise ConfigProviderError(scanned.name, f"{labels} exclude each other on one object")
        if matched:
            label, field = matched[0]
            if late and label in _EARLY_ONLY:
                raise ConfigProviderError(
                    scanned.name,
                    # A message split where it reads naturally.
                    f"{label} was found by a scan requested while loading bundles, "  # noqa: ISC003 — split for reading
                    + "after configs were resolved; put it in an early resource",
                )
            cast("list[ScannedObject]", getattr(result, field)).append(scanned)
            return
        if service_of(obj) is not None or aliases_of(obj):
            result.marked.append(scanned)
        result.services.append(scanned)

    def _put_aside(
        self,
        scanned: ScannedObject,
        held: object,
        module: str,
        set_aside: SetAsideModule,
        result: ScanResult,
    ) -> None:
        """Keep an object of a set-aside module out of the build; fail if it would be used.

        What the module holds in its place — a stand-in remembering it — is
        kept with it, for the autoconfiguration readers to be asked about too.

        Raises:
            SetAsideModuleUsedError: If it carries a marker of this package
                that a matching environment would act on.
        """
        obj = scanned.obj
        if is_excluded(obj):
            return
        if not matches_env(obj, self._env):
            self.skipped.append((scanned.name, _env_reason(obj, self._env)))
            return
        set_aside.defines.append(scanned.name)
        uses = [label for label, _, read in _QUEUES if read(obj) is not None]
        if tagged_item_of(obj) is not None:
            uses.append("@as_tagged_item")
        elif service_of(obj) is not None:
            uses.append("@as_service")
        if aliases_of(obj):
            uses.append("@as_alias")
        if autoconfigure_of(obj) is not None:
            uses.append("@autoconfigure")
        if autoconfigure_tags_of(obj):
            uses.append("@autoconfigure_tag")
        if uses:
            inspection = self._inspection
            explained = inspection.explain(module) if inspection is not None else set_aside
            raise SetAsideModuleUsedError(
                scanned.name,
                " and ".join(uses),
                module=module,
                missing=tuple(sorted(explained.missing)),
                through=explained.through,
            )
        result.set_aside.append(scanned)
        if held is not scanned.obj:
            result.set_aside.append(
                ScannedObject(
                    held,
                    scanned.name,
                    scanned.owner,
                    scanned.order,
                    in_environment_folder=scanned.in_environment_folder,
                )
            )


def _import(name: str) -> ModuleType:
    try:
        return importlib.import_module(name)
    except Exception as error:
        raise ResourceImportError(name) from error


def _env_reason(obj: object, env: str) -> str:
    included = when_envs_of(obj)
    if included is not None and env not in included:
        return f"@when({', '.join(sorted(included))}) excludes {env!r}"
    excluded = when_not_envs_of(obj) or frozenset()
    return f"@when_not({', '.join(sorted(excluded))}) excludes {env!r}"
