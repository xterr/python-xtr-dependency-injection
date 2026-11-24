"""Importing the application where a listed bundle is not active: setting aside what cannot import.

One :class:`Inspection` serves one application scan. Every module is imported
truthfully, with ``importlib.import_module``, and stays as that import left
it. A module whose import fails because a package it needs is not installed —
or because a module it imports is set aside — is **set aside**: kept here,
out of ``sys.modules``, with nothing it defines registered.

Nothing that is not what a truthful import produced is ever left in
``sys.modules``:

- a set-aside module that is loaded — its package failed after it — is taken
  out as it is, and never run again;
- one that is not is **inspected**: its code is run in a namespace of its own,
  never placed among the loaded modules but for the length of its own body,
  whose import statements alone are served — a stand-in for a package not
  installed, the namespace of a module set aside, and any other module as a
  truthful import gives it;
- that namespace answers its names to its own code and to what that code
  calls; read by another module — one a call of its body loaded, finding it
  among the loaded modules, or one holding it after the scan — it refuses, as
  importing it does;
- whatever else its body leaves in ``sys.modules`` is undone: a name it
  pointed elsewhere gets back what it held, and a name it added stays only if
  the import system loaded a module under it;
- for the scan's length, a :class:`~._refusal.RefusalFinder` refuses every
  set-aside name to every truthful import the scan's thread makes, so a
  module importing one fails as it would at runtime — naming the package a
  truthful import of it fails for — and is set aside in turn, or falls back,
  if it catches the failure.

Setting a package aside sets aside every module under it.

Private to the scan.
"""

from __future__ import annotations

import builtins
import importlib
import importlib.machinery
import importlib.util
import inspect
import sys
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import partial
from types import ModuleType
from typing import TYPE_CHECKING, ClassVar, Final, Self, cast, final, override

from xtr_dependency_injection.diagnostics.report import SetAsideReport
from xtr_dependency_injection.exception import ResourceImportError

from ._refusal import RefusalFinder, SetAsideRefused, holder_of
from ._stand_ins import StandInModule

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Mapping, Sequence
    from types import CodeType, FrameType, TracebackType

__all__ = ["LOCK", "Inspection", "SetAsideModule"]

LOCK: Final = threading.RLock()
"""Held for a whole inspecting scan: its refusal finder is the process's."""

_MARK: Final = "__xtr_set_aside__"
"""Held by the namespace of an inspected module: its name, and what it lacks."""

_OWN_PACKAGE: Final = "xtr_dependency_injection."
"""This package's frames are never who imported, when an error says where it came from."""

_SCAN_PACKAGE: Final = "xtr_dependency_injection.scan."
"""The scan's own modules read a set-aside namespace freely: the inspection is theirs."""


@final
class _Builtins(dict[str, object]):
    """The builtins an inspected module's code sees: the process's, read as they are now."""

    __hash__: ClassVar[None] = None  # A dict: unhashable, as every dict.

    def __missing__(self, key: str) -> object:
        return cast("object", vars(builtins)[key])


@dataclass(slots=True)
class SetAsideModule:
    """A module set aside, and why.

    Attributes:
        module: The module: as it was loaded, or the namespace its code ran in.
        missing: The top-level packages it needs that are not installed.
        through: The set-aside module it needs them through, or ``None`` when
            it imports one of them itself.
        expected: Whether it needs, or reaches, the package of a listed
            bundle that is not active.
        defines: ``module:qualname`` of each object it defines that the
            scan looked at.
        package: The nearest package it lies in that is set aside, if any.
        needs: The packages not installed its own imports asked for, in order.
        served: The set-aside modules its own imports were served, in order.
        reached: Every name its own imports asked for, in order.
        lacking: The package not installed its truthful import failed for,
            when it was imported truthfully: what a refusal of it names.
        views: Each loaded package its own imports bound, as it sees it —
            the set-aside modules under it grafted on.
    """

    module: ModuleType
    missing: set[str] = field(default_factory=set)
    through: str | None = None
    expected: bool = False
    defines: list[str] = field(default_factory=list)
    package: str | None = None
    needs: list[str] = field(default_factory=list)
    served: list[str] = field(default_factory=list)
    reached: list[str] = field(default_factory=list)
    lacking: str | None = None
    views: dict[str, _Branch] = field(default_factory=dict)


@final
class _Branch(ModuleType):
    """A loaded package as an inspected module sees it: set-aside children grafted, nothing changed.

    ``import app.fixtures`` binds ``app``, and ``from app import fixtures``
    reads it off ``app``: where ``app`` is loaded and ``app.fixtures`` set
    aside, the package itself must not hold the module. This holds it instead,
    and answers everything else as the package does.
    """

    def __init__(self, package: ModuleType) -> None:
        super().__init__(package.__name__)
        self._package = package
        self._grafted: dict[str, ModuleType] = {}
        # Set by the module type for every module: read off the package instead.
        for dunder in ("__doc__", "__package__", "__loader__", "__spec__"):
            setattr(self, dunder, getattr(package, dunder, None))

    def graft(self, name: str, module: ModuleType) -> None:
        """Hold ``module`` as this package's ``name``, for the inspected module seeing it."""
        self._grafted[name] = module

    @override
    def __getattr__(self, name: str) -> object:
        grafted = self._grafted.get(name)
        return grafted if grafted is not None else cast("object", getattr(self._package, name))


@final
class _Inspected(ModuleType):
    """The namespace an inspected module's code runs in: its names are for inspected code alone.

    Its own code reads its globals without asking it. Code it calls — a
    library looking it up (``inspect.getmembers``, ``pkgutil.resolve_name``) —
    is answered as well: the module's own body is up its stack. Code of
    another module is refused, as an import of the namespace is: a module a
    call of its body loaded, whose body is running instead, or one holding
    it after the scan. That holds for its ``__spec__`` too, which the import
    system reads to hand a loaded module back — so such a module cannot
    import it either. Every other dunder is answered to anyone: the
    standard library looks up a module's ``__dict__``, ``__path__`` and the
    like.
    """

    @override
    def __getattribute__(self, name: str) -> object:
        guarded = name == "__spec__" or not (name.startswith("__") and name.endswith("__"))
        if guarded:
            own = cast("dict[str, object]", super().__getattribute__("__dict__"))
            frame = inspect.currentframe()
            if _read_by_another_module(own, frame.f_back if frame is not None else None):
                inspected, lacking = cast("tuple[str, Callable[[str], str]]", own[_MARK])
                raise SetAsideRefused(inspected, inspected, lacking(inspected))
        return cast("object", super().__getattribute__(name))


def _read_by_another_module(own: Mapping[str, object], frame: FrameType | None) -> bool:
    """Whether code reading the namespace ``own`` is another module's, not what its body called.

    Up from the reader: the import system's frames say nothing; inspected
    code, or the scan's own, may read it, and so may ``importlib.util.find_spec``
    asking whether it exists; reaching the namespace's own code first, the
    read is made for it; reaching the body of another module first — one
    being imported — or the top of the stack, it is not.
    """
    while frame is not None:
        reader = frame.f_globals
        if reader is own:
            return False
        module = reader.get("__name__")
        if module == "importlib.util" and frame.f_code.co_name == "find_spec":
            return False
        importing = frame.f_code.co_filename.startswith("<frozen importlib") or (
            isinstance(module, str) and (module == "importlib" or module.startswith("importlib."))
        )
        if not importing:
            if _MARK in reader or (isinstance(module, str) and module.startswith(_SCAN_PACKAGE)):
                return False
            if frame.f_code.co_name == "<module>":
                return True
        frame = frame.f_back
    return True


@final
class Inspection:
    """Imports for one application scan, setting aside what needs a package not installed."""

    __slots__ = (
        "_application",
        "_failing",
        "_fatal",
        "_finder",
        "_inactive",
        "_loads",
        "_missing",
        "_open",
        "_running",
        "_set_aside",
        "_thread",
    )

    def __init__(self, application: tuple[str, ...], inactive_packages: frozenset[str]) -> None:
        """Inspect for an application under ``application``.

        Args:
            application: The application package and the resources its scan
                names: a module missing from one of them is never set aside.
            inactive_packages: The packages of the listed bundles that are
                not active — a top-level package, or the subpackage of the
                application a bundle of its own lives in — which make a
                set-aside module expected.
        """
        self._application = application
        self._inactive = inactive_packages
        self._missing: set[str] = set()
        self._set_aside: dict[str, SetAsideModule] = {}
        # Modules whose body a failed import ran through: importing one again fails again.
        # Each with the package not installed its failure named.
        self._failing: dict[str, str | None] = {}
        # Each module the scan's truthful imports loaded, in order: a body taking one out is undone.
        self._loads: list[tuple[str, ModuleType]] = []
        # The namespaces whose bodies are running, outermost first.
        self._running: list[ModuleType] = []
        self._fatal: ResourceImportError | None = None
        self._finder = RefusalFinder(self._set_aside, self._first_lacking)
        self._thread = threading.get_ident()
        self._open = False

    def __enter__(self) -> Self:
        """Start refusing what is set aside, to every import of this thread."""
        self._finder.install()
        self._open = True
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Stop refusing, and stop serving: what is set aside imports as anything does.

        What the scan kept to undo a body is let go: a set-aside function holds
        this inspection, through what serves its module's imports, for as long
        as the build keeps it.
        """
        del kind, error, traceback
        self._open = False
        self._finder.remove()
        self._loads.clear()
        self._failing.clear()
        self._running.clear()

    @property
    def set_aside(self) -> Mapping[str, SetAsideModule]:
        """Every module set aside so far, by name."""
        return self._set_aside

    def import_module(self, name: str) -> ModuleType:
        """Import ``name``, or set it aside when a package it needs is not installed.

        Raises:
            ResourceImportError: If it fails to import, and is not to be set
                aside, or its code fails with what it needs served.
        """
        try:
            module = self._load(name)
        except ResourceImportError:
            raise
        except Exception as error:
            raise ResourceImportError(name) from error
        if self._fatal is not None:
            # Raised inside an inspected body that caught it: it is fatal all the same.
            raise self._fatal
        return module

    def explain(self, name: str) -> SetAsideModule:
        """Return the set-aside ``name``, having worked out why: what it lacks, through which."""
        entry = self._set_aside[name]
        self._explain_one(name, entry)
        return entry

    def reports(self) -> list[SetAsideReport]:
        """Return what was set aside, as the scan report holds it, and forget it.

        Each namespace keeps what it lacks: read after the scan, it is refused
        naming that, though the scan's records are gone.
        """
        for name, entry in self._set_aside.items():
            self._explain_one(name, entry)
            if isinstance(entry.module, _Inspected):
                vars(entry.module)[_MARK] = (name, partial(_given, self._first_lacking(name)))
        reports = [
            SetAsideReport(
                module=name,
                missing=tuple(sorted(entry.missing)),
                through=entry.through,
                defines=tuple(entry.defines),
                expected=entry.expected,
            )
            for name, entry in self._set_aside.items()
        ]
        self._set_aside.clear()
        return reports

    # --- importing truthfully, and deciding what is set aside ---------------------------

    def _load(self, name: str) -> ModuleType:
        """Return ``name``: imported truthfully, or set aside. Its packages come first.

        Raises:
            ImportError: The failure of its truthful import, when that is not
                one to set it aside for — a missing-module error naming a
                package that is not installed among them, when ``name`` itself
                lies in that package.
            Exception: Whatever else its import raised.
        """
        found = self._set_aside.get(name)
        if found is not None:
            return found.module
        parent = name.rpartition(".")[0]
        if parent and parent not in sys.modules:
            # An orphan would be handed back from sys.modules with no finder asked.
            _ = self._load(parent)
        aside = name in self._failing or holder_of(name, self._set_aside) is not None
        loaded = sys.modules.get(name)
        if loaded is not None and not aside:
            # Loaded truthfully already: importing it again would load nothing.
            return loaded
        before = frozenset(sys.modules)
        if aside:
            entry = self._put_aside(name, self._failing.get(name))
            self._settle_orphans(_fresh(before))
            return entry.module
        try:
            with self._out_of_sight():
                module = importlib.import_module(name)
        except ImportError as error:
            failure = error
        else:
            fresh = _fresh(before)
            self._record_loads(fresh)
            self._settle_orphans(fresh)
            return module
        fresh = _fresh(before)
        self._record_loads(fresh)
        # Set aside outside the handler: what fails meanwhile is not raised over this failure.
        lacking = self._lacking_of(failure)
        if lacking is None or name.partition(".")[0] in self._missing:
            raise failure
        for body in _failed_bodies(failure):
            # A body the error ran through that loaded all the same caught it, and is healthy.
            if body not in sys.modules:
                _ = self._failing.setdefault(body, lacking)
        # What a truthful import of it fails for: a refusal of it says the same.
        entry = self._put_aside(name, lacking)
        self._settle_orphans(fresh)
        return entry.module

    def _record_loads(self, fresh: Sequence[str]) -> None:
        """Record the modules a truthful import made while a body runs: undoing it keeps them."""
        if self._running:
            self._loads.extend((entry, sys.modules[entry]) for entry in fresh)

    def _settle_orphans(self, fresh: Sequence[str]) -> None:
        """Settle the package of each module of ``fresh`` a truthful import left orphaned.

        A failed import caught by the module making it (``try: import
        app.fixtures``) leaves loaded what it loaded before failing, without
        its package: a later import would be handed it from ``sys.modules``,
        though its package fails. Its package — the application's, or an
        installed library's — is imported at once, and set aside, taking the
        orphan with it as it is, never run again: as the scan does whichever
        order it finds them in. One failing for a reason of its own is left as
        Python leaves it.
        """
        for orphan in sorted(fresh):
            parent = orphan.rpartition(".")[0]
            if not parent or parent in sys.modules or orphan not in sys.modules:
                continue
            if holder_of(orphan, self._set_aside) is not None:
                continue
            try:
                _ = self._load(parent)
            except ResourceImportError:
                raise
            except Exception:  # noqa: BLE001, S112 — the package's own failure: the scan meets it there
                continue

    @contextmanager
    def _out_of_sight(self) -> Generator[None]:
        """Take the namespace whose body is running out of ``sys.modules`` meanwhile.

        It sits there for its own code alone: a module imported truthfully
        while it runs must not find it, and what it holds, by its name.
        """
        running = self._running[-1] if self._running else None
        hidden = running is not None and sys.modules.get(running.__name__) is running
        if running is not None and hidden:
            del sys.modules[running.__name__]
        try:
            yield
        finally:
            if running is not None and hidden:
                sys.modules[running.__name__] = running

    def _lacking_of(self, failure: ImportError) -> str | None:
        """Return the package not installed ``failure`` sets its module aside for; ``None`` if none.

        A refusal names the package its set-aside module lacks; a package
        found not installed is noted as missing.
        """
        missing = _missing_module(failure)
        if missing is None:
            return None
        if isinstance(missing, SetAsideRefused):
            return missing.name
        package = self._not_installed(missing)
        if package is not None:
            self._missing.add(package)
        return package

    def _not_installed(self, missing: ModuleNotFoundError) -> str | None:
        """Return the top-level package ``missing`` names, when it is not installed.

        ``None`` — the failure is not one to set aside — for a module missing
        from the application, or from a package that is installed: that is a
        broken installation, or a mistake in the code.
        """
        if not missing.name:
            return None
        package = missing.name.partition(".")[0]
        if package in self._missing:
            return package
        if any(package == root.partition(".")[0] for root in self._application):
            return None
        if package in sys.modules:
            return None
        return package if importlib.util.find_spec(package) is None else None

    # --- setting aside ------------------------------------------------------------------

    def _put_aside(self, name: str, lacking: str | None = None) -> SetAsideModule:
        """Set ``name`` aside: as it is when loaded, else by running its code in a namespace.

        Its packages are settled already: each is loaded, or set aside.
        ``lacking`` is what its truthful import failed for, when it was tried.
        """
        found = self._set_aside.get(name)
        if found is not None:
            return found
        loaded = sys.modules.get(name)
        if loaded is not None:
            return self._adopt(name, loaded, lacking)
        return self._execute(name, lacking)

    def _adopt(self, name: str, loaded: ModuleType, lacking: str | None = None) -> SetAsideModule:
        """Take ``loaded`` out of the loaded modules, as it is: it ran truthfully, once."""
        _drop(name, loaded)
        entry = SetAsideModule(loaded, package=self._package_of(name), lacking=lacking)
        self._set_aside[name] = entry
        self._bind(name, loaded)
        _ = self._adopt_children(name)
        return entry

    def _adopt_children(self, name: str) -> list[str]:
        """Set aside every loaded module under ``name``, parents before their modules; name them."""
        children = sorted(
            entry
            for entry in sys.modules
            if entry.startswith(f"{name}.") and entry not in self._set_aside
        )
        for child in children:
            loaded = sys.modules.get(child)
            if loaded is not None and child not in self._set_aside:
                _ = self._adopt(child, loaded)
        return children

    def _package_of(self, name: str) -> str | None:
        """Return the nearest package ``name`` lies in that is set aside."""
        parent = name.rpartition(".")[0]
        return holder_of(parent, self._set_aside) if parent else None

    def _bind(self, name: str, module: ModuleType) -> None:
        """Set ``module`` on its package where that is set aside too, as its import would have.

        A loaded package is never touched: what an inspected module reads
        off one goes through a :class:`_Branch`.
        """
        parent, _, leaf = name.rpartition(".")
        holder = self._set_aside.get(parent)
        if holder is not None:
            setattr(holder.module, leaf, module)

    def _execute(self, name: str, lacking: str | None = None) -> SetAsideModule:
        """Run the code of ``name`` in a namespace of its own, its imports served.

        The namespace sits in ``sys.modules`` for its own body only: a
        dataclass, among others, looks its module up there by name. What the
        body did to ``sys.modules`` is undone after: a name it pointed
        elsewhere gets back what it held, and a name it added stays only if a
        truthful import loaded it.

        Raises:
            ModuleNotFoundError: If no module of that name is found where its
                package lies.
            ResourceImportError: If it has no code to run, or its code fails.
        """
        record = self._record_of(name)
        if record is None:
            raise ModuleNotFoundError(f"No module named {name!r}", name=name)
        code = _code_of(name, record)
        module = _namespace(name, record, self._first_lacking)
        entry = SetAsideModule(module, package=self._package_of(name), lacking=lacking)
        served = cast("object", partial(self._serve, entry))
        vars(module)["__builtins__"] = _Builtins({"__import__": served})
        # Recorded before it runs: refused to every truthful import, and served as it stands.
        self._set_aside[name] = entry
        adopted = self._adopt_children(name)
        with self._out_of_sight():
            self._running.append(module)
            loaded_before = dict(sys.modules)
            loads_before = len(self._loads)
            sys.modules[name] = module
            try:
                exec(code, vars(module))  # noqa: S102 — a module's own code, as its import runs it
            except ResourceImportError as error:
                self._fatal = error
                raise
            except Exception as error:
                # Not set aside after all: it is the failure of the scan.
                for dropped in (name, *adopted):
                    _ = self._set_aside.pop(dropped, None)
                self._fatal = _still_failing(name, error, entry, self._lacked(error))
                raise self._fatal from error
            finally:
                _ = self._running.pop()
                _ = sys.modules.pop(name, None)
                self._undo(loaded_before, self._loads[loads_before:])
        self._bind(name, module)
        return entry

    def _undo(
        self, loaded_before: Mapping[str, ModuleType], loaded: Sequence[tuple[str, ModuleType]]
    ) -> None:
        """Undo what a body running on stand-ins did to ``sys.modules`` itself.

        A name it pointed at something else holds what it held again; a name
        it added goes when what it holds is the scan's own — a stand-in, a
        view of a package, an inspected namespace — and stays otherwise: a
        module a truthful import loaded, or an alias a library made. A module
        it took out — one loaded before, or loaded by the scan for it — is
        put back, unless the scan set it aside meanwhile.
        """
        for key, value in list(sys.modules.items()):
            previous = loaded_before.get(key)
            if previous is value:
                continue
            if previous is not None:
                sys.modules[key] = previous
            elif isinstance(value, (StandInModule, _Branch, _Inspected)):
                del sys.modules[key]
        for key, previous in [*loaded_before.items(), *loaded]:
            # Taken out by the body itself — not set aside by the scan meanwhile.
            if key not in sys.modules and holder_of(key, self._set_aside) is None:
                sys.modules[key] = previous

    def _record_of(self, name: str) -> importlib.machinery.ModuleSpec | None:
        """Find the import record of ``name`` on its package's path, importing nothing."""
        parent = name.rpartition(".")[0]
        if not parent:
            return importlib.machinery.PathFinder.find_spec(name, None)
        found = self._set_aside.get(parent)
        holder = found.module if found is not None else sys.modules.get(parent)
        # Read where the import system sets it: a module ``__getattr__`` may answer any name.
        path = cast("Sequence[str] | None", vars(holder).get("__path__") if holder else None)
        return importlib.machinery.PathFinder.find_spec(name, path) if path is not None else None

    def _lacked(self, error: BaseException) -> str | None:
        """Return what ``error`` lacked that an inspected module's own imports are served."""
        missing = _missing_module(error)
        if isinstance(missing, SetAsideRefused):
            return missing.module
        return self._not_installed(missing) if missing is not None else None

    def _first_lacking(self, name: str) -> str:
        """Return the package not installed a truthful import of the set-aside ``name`` fails for.

        As :func:`_first_of` finds it; else, for a module the scan knows too
        little of, the first package found missing.
        """
        found = _first_of(name, self._set_aside, set())
        if found is not None:
            return found
        return min(self._missing) if self._missing else name.partition(".")[0]

    # --- serving the imports of an inspected module -------------------------------------

    def _serve(  # noqa: PLR0913, PLR0917 — the signature of builtins.__import__, after the entry
        self,
        entry: SetAsideModule,
        name: str,
        globals: Mapping[str, object] | None = None,  # noqa: A002 — the signature of builtins.__import__
        locals: Mapping[str, object] | None = None,  # noqa: A002 — the signature of builtins.__import__
        fromlist: Sequence[str] | None = (),
        level: int = 0,
    ) -> ModuleType:
        """Answer an import statement of the inspected module ``entry`` is.

        Once the scan is over, or on another thread, the import is the
        process's own: nothing is served.
        """
        if not self._open or threading.get_ident() != self._thread:
            return importlib.__import__(name, globals, locals, fromlist or (), level)
        absolute = name
        if level:
            package = globals.get("__package__") if globals is not None else None
            absolute = importlib.util.resolve_name(
                "." * level + name, package if isinstance(package, str) else None
            )
        parts = absolute.split(".")
        # Each package first, as an import does.
        views = [self._reach(entry, ".".join(parts[:end])) for end in range(1, len(parts) + 1)]
        if fromlist:
            return self._taken_from(entry, absolute, views[-1], fromlist)
        return self._rooted(entry, parts, views)

    def _reach(self, entry: SetAsideModule, name: str) -> ModuleType:
        """Return what ``entry``'s code gets for ``name``, recording why it is set aside."""
        entry.reached.append(name)
        root = name.partition(".")[0]
        if root not in self._missing:
            try:
                module = self._load(name)
            except ModuleNotFoundError:
                if root not in self._missing:
                    raise
            else:
                if name in self._set_aside and name not in entry.served:
                    entry.served.append(name)
                return module
        if root not in entry.needs:
            entry.needs.append(root)
        return StandInModule(name)

    def _taken_from(
        self, entry: SetAsideModule, name: str, module: ModuleType, fromlist: Sequence[str]
    ) -> ModuleType:
        """Return ``module`` for ``from name import ...``: a name it lacks may be a module of it.

        One that is set aside is read off the module's view of ``module``
        where that is loaded: the package itself is left as it is. ``*`` takes
        the names its ``__all__`` lists, as an import does, and every public
        name of the package where it lists none.
        """
        star = "*" in fromlist
        items = [item for item in fromlist if item != "*"]
        if star:
            listed = _read(module, "__all__")
            if isinstance(listed, (list, tuple)):
                items.extend(
                    item for item in cast("Sequence[object]", listed) if isinstance(item, str)
                )
        entry.reached.extend(f"{name}.{item}" for item in items)
        if isinstance(module, StandInModule):
            return module
        for item in items:
            if _read(module, item) is not _ABSENT:
                continue
            child = f"{name}.{item}"
            try:
                found = self._reach(entry, child)
            except ModuleNotFoundError as error:
                if error.name != child:
                    raise
                # No such module: the statement fails for the name, as it would.
                continue
            if found is not sys.modules.get(child) and name not in self._set_aside:
                _ = _graft(entry, module, item, found)
        if star and _read(module, "__all__") is _ABSENT:
            # A view holds none of the package's names itself: ``*`` takes them off the package.
            return module
        return _view(entry, module)

    def _rooted(
        self, entry: SetAsideModule, parts: Sequence[str], views: Sequence[ModuleType]
    ) -> ModuleType:
        """Return what ``import a.b.c`` binds: ``a``, holding what is set aside under it.

        A loaded package is bound as the module's one view of it, so a later
        statement binding it again keeps what an earlier one grafted on.
        """
        view = views[-1]
        for index in range(len(views) - 2, -1, -1):
            holder = views[index]
            child = ".".join(parts[: index + 2])
            ours = (
                isinstance(holder, StandInModule) or ".".join(parts[: index + 1]) in self._set_aside
            )
            if ours:
                view = holder
            elif view is sys.modules.get(child):
                view = _view(entry, holder)
            else:
                view = _graft(entry, holder, parts[index + 1], view)
        return _view(entry, view)

    # --- saying why ---------------------------------------------------------------------

    def _explain_one(self, name: str, entry: SetAsideModule) -> None:
        """Work out why ``name`` is set aside: what it lacks, through which, expected or not.

        Done when it is read — for the report, or for an error naming it — not
        after every import: the answer depends on every module set aside
        before it, and on nothing after.
        """
        entry.missing = self._missing_of(name, set())
        entry.expected = self._expected(name, set())
        # The first module served that lacks something other than through this one.
        entry.through = (
            None
            if entry.needs
            else next(
                (
                    served
                    for served in entry.served
                    if holder_of(name, (served,)) is None and self._missing_of(served, {name})
                ),
                entry.package,
            )
        )

    def _missing_of(self, name: str, seen: set[str]) -> set[str]:
        entry = self._set_aside.get(name)
        if entry is None or name in seen:
            return set()
        seen.add(name)
        missing = set(entry.needs)
        for source in (*entry.served, entry.package):
            if source is not None:
                missing |= self._missing_of(source, seen)
        return missing

    def _expected(self, name: str, seen: set[str]) -> bool:
        entry = self._set_aside.get(name)
        if entry is None or name in seen:
            return False
        seen.add(name)
        # Every package it needs is the root of a name it reached.
        if any(holder_of(target, self._inactive) for target in entry.reached):
            return True
        return any(
            self._expected(source, seen)
            for source in (*entry.served, entry.package)
            if source is not None
        )


def _missing_module(error: BaseException) -> ModuleNotFoundError | None:
    """Return ``error`` if a module is missing, else the missing-module error it was raised over.

    Read through an import error naming no module — a library's "install the
    extra" — or naming the package found missing. One naming another module
    (``cannot import name 'X' from 'app.y'``) is a failure of its own,
    whatever it was raised over.
    """
    seen: set[int] = set()
    named: str | None = None
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        if isinstance(current, ModuleNotFoundError):
            found = current.name.partition(".")[0] if current.name else None
            return current if named is None or found == named else None
        if isinstance(current, ImportError) and current.name is not None and named is None:
            named = current.name.partition(".")[0]
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return None


def _failed_bodies(error: BaseException) -> list[str]:
    """Return the modules whose bodies ``error`` ran through: each failed to import with it."""
    bodies: list[str] = []
    traceback: TracebackType | None = error.__traceback__
    while traceback is not None:
        frame = traceback.tb_frame
        name = frame.f_globals.get("__name__")
        if frame.f_code.co_name == "<module>" and isinstance(name, str):
            bodies.append(name)
        traceback = traceback.tb_next
    return bodies


def _code_of(name: str, record: importlib.machinery.ModuleSpec | None) -> CodeType:
    """Return the code of the module ``record`` was found for.

    Raises:
        ResourceImportError: If it has none to run in a namespace: it is not
            found where its package lies, or is not written in Python.
    """
    loader = record.loader if record is not None else None
    get_code = cast("object", getattr(loader, "get_code", None))
    code = cast("CodeType | None", get_code(name)) if callable(get_code) else None
    if code is None:
        failure = ResourceImportError(name)
        failure.add_note(
            "it needs a package that is not installed here; it has no code to run again"
        )
        raise failure
    return code


def _view(entry: SetAsideModule, module: ModuleType) -> ModuleType:
    """Return how ``entry``'s code sees ``module``: its view of a loaded package, if it has one."""
    if isinstance(module, (StandInModule, _Branch, _Inspected)):
        return module
    return entry.views.get(module.__name__, module)


def _graft(entry: SetAsideModule, package: ModuleType, child: str, module: ModuleType) -> _Branch:
    """Graft ``module`` on ``entry``'s one view of the loaded ``package``, made at the first.

    Made, it takes the place of the package wherever the inspected module
    bound the package already (``from app import fixtures`` before ``import
    app.fixtures.users``), so every name for it sees what is grafted.
    """
    view = entry.views.get(package.__name__)
    if view is None:
        view = _Branch(package)
        entry.views[package.__name__] = view
        # Only an inspected module's code is served, so its namespace is the one to rebind.
        namespace = cast("dict[str, object]", vars(entry.module))
        for bound in [key for key, value in namespace.items() if value is package]:
            namespace[bound] = view
    view.graft(child, module)
    return view


_ABSENT: Final = object()
"""What :func:`_read` gives for a name a module does not have."""


def _given(lacking: str, name: str) -> str:
    """Return ``lacking`` whatever ``name``: what a namespace lacks, kept past the scan."""
    del name
    return lacking


def _read(module: ModuleType, name: str) -> object:
    """Return ``module``'s ``name``, or :data:`_ABSENT` — also when reading it fails an import.

    A package answering a name lazily (a module ``__getattr__``) may import a
    module to answer it that is, or turns out to be, set aside: the name is
    not there yet, and the scan serves the module it names instead. A failure
    of another kind is raised again when the statement reads the name itself.
    """
    try:
        found: object = getattr(module, name, _ABSENT)
    except ImportError:
        return _ABSENT
    return found


def _first_of(name: str, set_aside: Mapping[str, SetAsideModule], seen: set[str]) -> str | None:
    """Return the package not installed a truthful import of the set-aside ``name`` fails for.

    The one its truthful import failed for, when it was tried; else, in the
    order its own imports asked, the first package not installed, or the first
    set-aside module that lacks one; else what its package lacks.
    """
    entry = set_aside.get(name)
    if entry is None or name in seen:
        return None
    seen.add(name)
    if entry.lacking is not None:
        return entry.lacking
    for target in entry.reached:
        root = target.partition(".")[0]
        if root in entry.needs:
            return root
        if target != name and target in set_aside:
            found = _first_of(target, set_aside, seen)
            if found is not None:
                return found
    return _first_of(entry.package, set_aside, seen) if entry.package is not None else None


def _namespace(
    name: str, record: importlib.machinery.ModuleSpec, lacking: Callable[[str], str]
) -> ModuleType:
    """Return a module for the code of ``name`` to run in, named as its import would name it."""
    module = _Inspected(name)
    locations = record.submodule_search_locations
    module.__spec__ = record
    module.__loader__ = record.loader
    module.__package__ = name if locations is not None else name.rpartition(".")[0]
    if record.origin is not None:
        module.__file__ = record.origin
    if locations is not None:
        module.__path__ = list(locations)
    vars(module)[_MARK] = (name, lacking)
    return module


def _still_failing(
    name: str, error: BaseException, entry: SetAsideModule, lacked: str | None
) -> ResourceImportError:
    """Return the failure of ``name``, run again with what its imports ask for served.

    ``lacked`` is what the error lacked that only the module's own imports are served.
    """
    failure = ResourceImportError(name)
    if entry.needs:
        packages = ", ".join(repr(package) for package in sorted(entry.needs))
        served = f"with {packages} stood in for — not installed here —"
    else:
        served = "with the modules it needs set aside given back"
    note = f"imported again {served} to see what it defines, it failed with {error!r}"
    where, called = _origin(error)
    if lacked == name:
        note += f"; its names are given only to its own code, and to what it calls — not to {where}"
    elif lacked is not None:
        made = (
            f"importlib.import_module, called by {where}"
            if called
            else (f"an import statement of {where}")
        )
        note += (
            f"; {lacked!r} is served only to this module's own import statements — not to {made}"
        )
    elif where != f"{name}:<module>":
        note += f"; raised in {where}"
    failure.add_note(note)
    return failure


def _origin(error: BaseException) -> tuple[str, bool]:
    """Return the innermost code of the application or a library ``error`` came out of.

    ``module:qualname``, or ``code naming no module``; and whether it reached
    the failure through ``importlib.import_module``. The frames of the import
    system, of the standard library and of this scan are not who imported.
    """
    traceback: TracebackType | None = error.__traceback__
    where = "code naming no module"
    called = False
    while traceback is not None:
        frame = traceback.tb_frame
        module = frame.f_globals.get("__name__")
        frozen = frame.f_code.co_filename.startswith("<frozen importlib")
        standard = isinstance(module, str) and module.partition(".")[0] in sys.stdlib_module_names
        if module == "importlib" and frame.f_code.co_name == "import_module":
            called = True
        elif frozen or standard or (isinstance(module, str) and module.startswith(_OWN_PACKAGE)):
            pass
        elif isinstance(module, str):
            where = f"{module}:{frame.f_code.co_qualname}"
            called = False
        else:
            where = "code naming no module"
            called = False
        traceback = traceback.tb_next
    return where, called


def _fresh(before: frozenset[str]) -> list[str]:
    """Return the names loaded since ``before``, in the order they were loaded."""
    return [entry for entry in sys.modules if entry not in before]


def _drop(name: str, module: ModuleType) -> None:
    """Take ``module`` out of ``sys.modules``, and off its package where that is loaded."""
    if sys.modules.get(name) is module:
        del sys.modules[name]
    parent, _, child = name.rpartition(".")
    holder = sys.modules.get(parent) if parent else None
    if holder is not None and vars(holder).get(child) is module:
        delattr(holder, child)
