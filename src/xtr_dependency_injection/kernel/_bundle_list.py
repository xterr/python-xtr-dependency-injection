"""Reading an application's bundle list, even where a package it imports is not installed.

The list, ``<package>/config/bundles.py``, imports every bundle class it maps
to environments — a development tool's too — while a deployment installs the
runtime dependencies only. When importing the list fails for a package outside
the application, the list is imported once more with each package it imports
and that is not installed stood in for: every name taken from one is an
:class:`AbsentBundle`, which the resolver reports as disabled, or refuses where
its flags make it active.

Nothing else is stood in for. A module the list pulls in imports what it
imports as it always does, so one that needs a missing package still fails; a
module missing from a package that is installed — the application's own
included — is a broken installation, and fails too.
"""

from __future__ import annotations

import importlib
import importlib.abc
import importlib.machinery
import inspect
import sys
from collections.abc import Mapping
from types import ModuleType
from typing import TYPE_CHECKING, Final, cast, final

from typing_extensions import override

from xtr_dependency_injection.bundle._absent_bundle import AbsentBundle
from xtr_dependency_injection.bundle.bundle import AnyBundle, Bundle
from xtr_dependency_injection.exception import BundleDefinitionError, ResourceImportError

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["load_bundle_list"]

#: Where an application's bundle list is read from, in the order looked for:
#: beside the rest of its configuration, then where an earlier layout put it.
_BUNDLES_MODULES: Final = ("config.bundles", "bundles")


def load_bundle_list(
    package_name: str,
) -> Mapping[type[AnyBundle] | AbsentBundle, Mapping[str, bool]]:
    """Import ``<package_name>.config.bundles`` and return its ``BUNDLES`` mapping.

    An application written before the bundle list joined its configuration
    keeps it at ``<package_name>.bundles``, which is read when the first is
    absent. Both are optional (neither yields an empty mapping), but a module
    that does exist must expose ``BUNDLES``.

    Raises:
        ResourceImportError: If the bundle list exists but a deeper import
            fails, even with each package it imports and that is not
            installed stood in for.
        BundleDefinitionError: If the module is present but lacks ``BUNDLES``,
            or if a listed class is not a decorated :class:`Bundle`.
    """
    application = package_name.partition(".")[0]
    for suffix in _BUNDLES_MODULES:
        module = _bundles_module(f"{package_name}.{suffix}", application)
        if module is not None:
            return _listed_bundles(module)
    return {}


def _bundles_module(module_name: str, application: str) -> ModuleType | None:
    """Import ``module_name``, or return ``None`` when it does not exist.

    Raises:
        ResourceImportError: If the module exists but a deeper import fails.
    """
    try:
        return importlib.import_module(module_name)
    except ModuleNotFoundError as error:
        # Absent itself, or absent because the package it sits in is: either
        # way there is no bundle list here.
        missing = error.name
        if missing is not None and f"{module_name}.".startswith(f"{missing}."):
            return None
        # The application's own modules are all there, or it is broken.
        if missing is None or missing == application or missing.startswith(f"{application}."):
            raise ResourceImportError(module_name) from error
    except ImportError as error:
        raise ResourceImportError(module_name) from error
    return _import_standing_in(module_name)


def _import_standing_in(module_name: str) -> ModuleType:
    """Import ``module_name`` again, standing in for each package it imports that is missing.

    The finder and every stand-in are taken away whether or not the import
    succeeds: nothing imported afterwards ever finds one.

    Raises:
        ResourceImportError: If the import still fails.
    """
    finder = _StandInFinder(module_name)
    # The failed attempt dropped the module already; the second runs it afresh.
    _ = sys.modules.pop(module_name, None)
    # Last of all finders, so a module any of them finds is imported as ever.
    sys.meta_path.append(finder)
    try:
        return importlib.import_module(module_name)
    except ImportError as error:
        raise ResourceImportError(module_name) from error
    finally:
        sys.meta_path.remove(finder)
        for name in finder.stood_in:
            _ = sys.modules.pop(name, None)


def _listed_bundles(
    module: ModuleType,
) -> Mapping[type[AnyBundle] | AbsentBundle, Mapping[str, bool]]:
    """Return the ``BUNDLES`` mapping ``module`` declares, checked entry by entry.

    A class imported from a package that is not installed is listed as the
    :class:`AbsentBundle` standing in for it.

    Raises:
        BundleDefinitionError: If the module lacks ``BUNDLES``, or a listed
            class is not a decorated :class:`Bundle`.
    """
    module_name = module.__name__
    raw = getattr(module, "BUNDLES", None)
    if raw is None:
        raise BundleDefinitionError(module_name, "it does not define BUNDLES")
    if not isinstance(raw, Mapping):
        raise BundleDefinitionError(
            module_name, "BUNDLES must be a mapping of bundle class to activity flags"
        )
    result: dict[type[AnyBundle] | AbsentBundle, Mapping[str, bool]] = {}
    # An application's BUNDLES, checked entry by entry below.
    for cls, flags in raw.items():  # pyright: ignore[reportUnknownVariableType]
        cls_obj = cast("object", cls)
        listed: type[AnyBundle] | AbsentBundle
        if isinstance(cls_obj, AbsentBundle):
            listed = cls_obj
        elif isinstance(cls_obj, type) and issubclass(cls_obj, Bundle):
            listed = cast("type[AnyBundle]", cls_obj)
        else:
            raise BundleDefinitionError(
                module_name, f"{cls_obj!r} listed in BUNDLES is not a Bundle subclass"
            )
        if not isinstance(flags, Mapping):
            raise BundleDefinitionError(
                module_name, f"activity flags for {cls_obj!r} must be a mapping"
            )
        result[listed] = dict(cast("Mapping[str, bool]", flags))
    return result


@final
class _StandInFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Stands in for each package a bundle list imports and that no other finder finds.

    Only an import the list's own code makes is answered, so a module the list
    pulls in learns the truth about what is installed — one probing for an
    optional dependency included. And only a package that is not installed at
    all is stood in for: a module missing from one that is — the application's
    own included — is a broken installation.

    Attributes:
        stood_in: The modules stood in for, parents before their modules.
    """

    def __init__(self, bundles_module: str) -> None:
        """Answer the imports ``bundles_module`` makes."""
        self._bundles_module = bundles_module
        self.stood_in: list[str] = []

    @override
    def find_spec(
        self,
        fullname: str,
        path: Sequence[str] | None,
        target: ModuleType | None = None,
    ) -> importlib.machinery.ModuleSpec | None:
        """Answer for ``fullname`` with a stand-in, or with ``None`` to leave it missing."""
        del path, target
        parent = fullname.rpartition(".")[0]
        if parent and parent not in self.stood_in:
            return None
        if not _imported_by(self._bundles_module):
            return None
        return importlib.machinery.ModuleSpec(fullname, self, is_package=True)

    @override
    def create_module(self, spec: importlib.machinery.ModuleSpec) -> ModuleType:
        """Return a stand-in for the module the import system asks for."""
        return _StandInModule(spec.name)

    @override
    def exec_module(self, module: ModuleType) -> None:
        """Record the stand-in, to take it away once the list is read."""
        self.stood_in.append(module.__name__)


@final
class _StandInModule(ModuleType):
    """A module of a package that is not installed: every name taken from it is absent.

    A name is answered with the same stand-in each time it is taken.
    """

    def __init__(self, name: str) -> None:
        """Stand in for the module ``name``."""
        super().__init__(name)
        self._absent: dict[str, AbsentBundle] = {}

    @override
    def __getattr__(self, name: str) -> AbsentBundle:
        """Return the stand-in for the class ``name`` would have been.

        A dunder is the import system asking about the module itself, and is
        answered as by any module without it.
        """
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        return self._absent.setdefault(name, AbsentBundle(self.__name__, name))


def _imported_by(module_name: str) -> bool:
    """Whether the import being looked up is one ``module_name``'s own code makes.

    A finder is not told who imports, so the stack says: the innermost module
    body on it belongs to the module whose import is running, and every frame
    nearer is the import system's, an import hook's, or a function that module
    called.
    """
    frame = inspect.currentframe()
    while frame is not None and frame.f_code.co_name != "<module>":
        frame = frame.f_back
    return frame is not None and frame.f_globals.get("__name__") == module_name
