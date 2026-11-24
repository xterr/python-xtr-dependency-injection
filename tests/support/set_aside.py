"""Scanning a throwaway application where packages are missing, and checking what is left.

A *scenario* is a mapping of module to source, written with roles in braces
(``{fx}``, ``{other}``) in place of module names; a *naming* gives each role a
name, so one scenario is scanned in more than one order. An *outcome* says
what the scan made of it, role by role, for two namings to be compared.

``acme_tools`` and ``acme_faker`` are never written: neither is installed.
"""

from __future__ import annotations

import builtins
import importlib
import sys
from contextlib import contextmanager
from typing import TYPE_CHECKING, cast

from xtr_dependency_injection.exception import DependencyInjectionError
from xtr_dependency_injection.scan import DEFAULT_EXCLUDES
from xtr_dependency_injection.scan._stand_ins import STAND_IN_ATTRIBUTE, StandIn, StandInModule
from xtr_dependency_injection.scan.scanner import Scanner, ScanResult

if TYPE_CHECKING:
    from collections.abc import Generator, Iterator, Mapping
    from pathlib import Path

    from xtr_dependency_injection.scan.scanned_object import ScannedObject

APP = "acme_app"

REGISTRY = """
NAMES: list[str] = []


def register(name):
    if name in NAMES:
        raise RuntimeError(f"{name} already registered")
    NAMES.append(name)
"""


def write(root: Path, modules: Mapping[str, str]) -> None:
    """Write each module (dotted name, ``.__init__`` for a package's own) under ``root``."""
    for module, source in modules.items():
        *packages, leaf = module.split(".")
        directory = root
        for package in packages:
            directory /= package
            directory.mkdir(exist_ok=True)
            init = directory / "__init__.py"
            if not init.exists():
                _ = init.write_text("")
        _ = (directory / f"{leaf}.py").write_text(source)
    importlib.invalidate_caches()


@contextmanager
def site(root: Path) -> Generator[None]:
    """Put ``root`` on ``sys.path``, and take every module loaded meanwhile away afterwards."""
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    before = frozenset(sys.modules)
    sys.path.insert(0, str(root))
    importlib.invalidate_caches()
    try:
        yield
    finally:
        sys.path.remove(str(root))
        # Whatever the scan left behind too, with a file or none: the next scan starts afresh.
        for name in [name for name in sys.modules if name not in before]:
            del sys.modules[name]
        importlib.invalidate_caches()


def _stands_in(obj: object) -> bool:
    """Whether ``obj`` is a stand-in, or a class derived from one.

    Read off its type: an object may answer for its class with code of its own.
    """
    kind = type(obj)
    if kind is StandIn or kind is StandInModule:
        return True
    if not issubclass(kind, type):
        return False
    return any(STAND_IN_ATTRIBUTE in vars(base) for base in cast("type", obj).__mro__)


def _held(module: object) -> Iterator[tuple[str, object]]:
    """Yield what a module holds: each name of its own, and each of the classes it holds."""
    for name, value in list(cast("dict[str, object]", vars(module)).items()):
        yield name, value
        if issubclass(type(value), type):
            attributes = cast("dict[str, object]", dict(vars(cast("type", value))))
            for attribute, held in attributes.items():
                yield f"{name}.{attribute}", held


def violations(
    scanner: Scanner,
    result: ScanResult | None,
    *,
    loaded_before: frozenset[str],
    meta_path: list[object],
    import_function: object,
) -> list[str]:
    """Return every way the scan left the process other than truthful imports would have."""
    found: list[str] = []
    fresh = [name for name in sys.modules if name not in loaded_before]
    set_aside = {entry.module for entry in scanner.set_aside}
    for name in fresh:
        module = sys.modules[name]
        if isinstance(module, StandInModule):
            found.append(f"{name} is a stand-in module left loaded")
            continue
        if name in set_aside:
            found.append(f"{name} is set aside and left loaded")
        parent = name.rpartition(".")[0]
        if parent and parent not in sys.modules:
            found.append(f"{name} is left loaded without its package {parent}")
        found.extend(
            f"{name}:{held} holds a stand-in" for held, value in _held(module) if _stands_in(value)
        )
    if result is not None:
        registered = [
            s
            for queue in ScanResult.__dataclass_fields__
            if queue != "set_aside"
            for s in cast("list[object]", getattr(result, queue))
        ]
        found.extend(
            f"{scanned.name} is registered and stands in"
            for scanned in cast("list[ScannedObject]", registered)
            if _stands_in(scanned.obj)
        )
    found.extend(
        f"{entry.module} is set aside for no missing package"
        for entry in scanner.set_aside
        if not entry.missing
    )
    if list(sys.meta_path) != meta_path:
        found.append("sys.meta_path is not as it was")
    if builtins.__import__ is not import_function:
        found.append("builtins.__import__ is not as it was")
    return found


def _named(text: str, naming: Mapping[str, str]) -> str:
    """Write ``text`` with each role in braces replaced by its name."""
    for role, name in naming.items():
        text = text.replace("{" + role + "}", name)
    return text


def _by_role(text: str | None, naming: Mapping[str, str]) -> str | None:
    """Write ``text`` with each name replaced by its role in braces, longest name first."""
    if text is None:
        return None
    for role, name in sorted(naming.items(), key=lambda item: -len(item[1])):
        text = text.replace(name, "{" + role + "}")
    return text


def _plain_values(module: object) -> dict[str, object]:
    """Return the flags and constants a module holds: what a probing module learnt."""
    return {
        name: value
        for name, value in cast("dict[str, object]", vars(module)).items()
        if not name.startswith("_") and (value is None or isinstance(value, (bool, int, str)))
    }


def scan_as(
    root: Path, scenario: Mapping[str, str], naming: Mapping[str, str]
) -> dict[str, object]:
    """Scan ``scenario`` written under ``root`` with ``naming``; return its outcome by role."""
    modules = {
        _named(module, naming): _named(source, naming) for module, source in scenario.items()
    }
    with site(root):
        write(root, {f"{APP}.__init__": "", "acme_registry.__init__": REGISTRY, **modules})
        before = frozenset(sys.modules)
        meta_path, import_function = list(sys.meta_path), builtins.__import__
        scanner = Scanner(
            env="prod", exclude=DEFAULT_EXCLUDES, package=APP, inactive_packages=("acme_tools",)
        )
        result: ScanResult | None = None
        failure: DependencyInjectionError | None = None
        try:
            result = scanner.scan([APP], owner=None)
        except DependencyInjectionError as error:
            failure = error
        registry = sys.modules.get("acme_registry")
        return {
            "failure": None
            if failure is None
            else [type(failure).__name__, _by_role(getattr(failure, "module", None), naming)],
            "services": sorted(
                _by_role(scanned.name, naming) or ""
                for scanned in (result.services if result else ())
            ),
            "set_aside": {
                _by_role(entry.module, naming): [
                    list(entry.missing),
                    _by_role(entry.through, naming),
                    entry.expected,
                    sorted(_by_role(name, naming) or "" for name in entry.defines),
                ]
                for entry in sorted(scanner.set_aside, key=lambda entry: entry.module)
            },
            "registered": list(cast("list[str]", vars(registry)["NAMES"])) if registry else [],
            "learnt": {
                _by_role(name, naming): _plain_values(sys.modules[name])
                for name in sorted(sys.modules)
                if name.startswith(f"{APP}.") and name not in before
            },
            "violations": violations(
                scanner,
                result,
                loaded_before=before,
                meta_path=cast("list[object]", meta_path),
                import_function=import_function,
            ),
        }
