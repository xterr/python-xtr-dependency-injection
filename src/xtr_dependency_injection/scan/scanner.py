"""Importing resources and sorting what they define.

The scan imports a package's modules, sorted by name, and looks only at the
functions and classes each module *defines* — an imported name belongs to the
module that defined it. Every object found goes to exactly one place: a
queue for its marker (``@configure``, ``@on_boot``…), or the service
candidates autoconfiguration looks at. An object excluded, or left out of the
environment, goes nowhere; the latter is reported.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from types import ModuleType
from typing import TYPE_CHECKING, Final, cast, final

from xtr_dependency_injection.compiler._wireup_bridge import declaration_of
from xtr_dependency_injection.config.configure import configure_of
from xtr_dependency_injection.config.parameters import is_parameters
from xtr_dependency_injection.decorator.as_decorator import decorator_of
from xtr_dependency_injection.decorator.compiler_pass import compiler_pass_of
from xtr_dependency_injection.decorator.exclude import is_excluded
from xtr_dependency_injection.decorator.lifecycle import on_boot_of, on_shutdown_of
from xtr_dependency_injection.decorator.when import matches_env, when_envs_of, when_not_envs_of
from xtr_dependency_injection.exception import ConfigProviderError, ResourceImportError

from .scanned_object import ScannedObject

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence

__all__ = ["ScanResult", "Scanner"]

_QUEUES: Final[tuple[tuple[str, Callable[[object], object]], ...]] = (
    ("@configure", configure_of),
    ("@parameters", lambda obj: is_parameters(obj) or None),
    ("@compiler_pass", compiler_pass_of),
    ("@on_boot", on_boot_of),
    ("@on_shutdown", on_shutdown_of),
    ("@as_decorator", decorator_of),
)
_EARLY_ONLY: Final = frozenset({"@configure", "@parameters"})


@dataclass(slots=True)
class ScanResult:
    """What one scan found, sorted by where each object goes.

    Attributes:
        configure: ``@configure`` providers.
        parameters: ``@parameters`` providers.
        compiler_passes: ``@compiler_pass`` functions.
        on_boot: ``@on_boot`` hooks.
        on_shutdown: ``@on_shutdown`` hooks.
        decorators: ``@as_decorator`` classes and factories.
        declared: Objects marked with wireup's ``@injectable``.
        services: Every service candidate — the declared ones included —
            for autoconfiguration.
    """

    configure: list[ScannedObject] = field(default_factory=list)
    parameters: list[ScannedObject] = field(default_factory=list)
    compiler_passes: list[ScannedObject] = field(default_factory=list)
    on_boot: list[ScannedObject] = field(default_factory=list)
    on_shutdown: list[ScannedObject] = field(default_factory=list)
    decorators: list[ScannedObject] = field(default_factory=list)
    declared: list[ScannedObject] = field(default_factory=list)
    services: list[ScannedObject] = field(default_factory=list)


@final
class Scanner:
    """Scans resources for one build: early, then late, never finding an object twice."""

    __slots__ = ("_env", "_exclude", "_order", "_seen", "modules", "skipped")

    def __init__(self, *, env: str, exclude: Sequence[str]) -> None:
        """Scan for ``env``, leaving out modules matching the ``exclude`` patterns."""
        self._env = env
        self._exclude = tuple(exclude)
        self._seen: set[int] = set()
        self._order = 0
        self.modules: list[str] = []
        self.skipped: list[tuple[str, str]] = []

    def scan(
        self, resources: Sequence[str | ModuleType], *, owner: str | None, late: bool = False
    ) -> ScanResult:
        """Import ``resources`` and sort what they define.

        Args:
            resources: Packages (walked recursively) or plain modules.
            owner: The bundle the resources belong to; ``None`` for the
                application.
            late: Whether this scan runs after configs are resolved, as one
                a bundle requested while loading does.

        Raises:
            ResourceImportError: If a module fails to import.
            ConfigProviderError: If an object carries two queue markers, or a
                late scan finds a ``@configure`` or ``@parameters``.
        """
        result = ScanResult()
        for module in self._modules(resources):
            for scanned in self._candidates(module, owner):
                self._classify(scanned, result, late=late)
        return result

    def _modules(self, resources: Sequence[str | ModuleType]) -> Iterator[ModuleType]:
        for resource in resources:
            root = resource if isinstance(resource, ModuleType) else _import(resource)
            yield from self._walk(root)

    def _walk(self, module: ModuleType) -> Iterator[ModuleType]:
        if module.__name__ not in self.modules:
            self.modules.append(module.__name__)
        yield module
        path = cast("list[str] | None", getattr(module, "__path__", None))
        if path is None:
            return
        children = sorted(pkgutil.iter_modules(path, f"{module.__name__}."), key=lambda m: m.name)
        for child in children:
            if not self._excluded(child.name):
                yield from self._walk(_import(child.name))

    def _excluded(self, name: str) -> bool:
        return any(fnmatchcase(name, pattern) for pattern in self._exclude)

    def _candidates(self, module: ModuleType, owner: str | None) -> Iterator[ScannedObject]:
        for obj in cast("list[object]", list(vars(module).values())):
            if not (inspect.isfunction(obj) or inspect.isclass(obj)):
                continue
            if getattr(obj, "__module__", None) != module.__name__ or id(obj) in self._seen:
                continue
            self._seen.add(id(obj))
            self._order += 1
            yield ScannedObject(obj, f"{module.__name__}:{obj.__qualname__}", owner, self._order)

    def _classify(self, scanned: ScannedObject, result: ScanResult, *, late: bool) -> None:
        obj = scanned.obj
        if is_excluded(obj):
            return
        if not matches_env(obj, self._env):
            self.skipped.append((scanned.name, _env_reason(obj, self._env)))
            return
        markers = [label for label, read in _QUEUES if read(obj) is not None]
        if len(markers) > 1:
            raise ConfigProviderError(
                scanned.name, f"{' and '.join(markers)} exclude each other on one object"
            )
        if markers:
            if late and markers[0] in _EARLY_ONLY:
                raise ConfigProviderError(
                    scanned.name,
                    f"{markers[0]} was found by a scan requested while loading bundles, "  # noqa: ISC003
                    + "after configs were resolved; put it in an early resource",
                )
            _queue(result, markers[0]).append(scanned)
            return
        if declaration_of(obj) is not None:
            result.declared.append(scanned)
        result.services.append(scanned)


def _queue(result: ScanResult, marker: str) -> list[ScannedObject]:
    return {
        "@configure": result.configure,
        "@parameters": result.parameters,
        "@compiler_pass": result.compiler_passes,
        "@on_boot": result.on_boot,
        "@on_shutdown": result.on_shutdown,
        "@as_decorator": result.decorators,
    }[marker]


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
