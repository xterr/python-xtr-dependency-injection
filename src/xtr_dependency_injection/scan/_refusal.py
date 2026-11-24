"""Refusing to load a set-aside module, for the length of one inspecting scan.

A module set aside is not loaded: importing it fails, as it would at runtime.
While the scan goes on, its file is still there to be found, and finding it
would run it again — truthfully, so failing again, or worse, half-way. One
:class:`RefusalFinder`, first of all finders, keeps that from happening: a
name that is, or lies under, a set-aside module is refused with
:class:`SetAsideRefused`, which any ``except ImportError`` catches.

It serves nothing. Asked only whether such a module exists
(``importlib.util.find_spec``), it answers as the other finders do, with a
copy of the record they found — whose loader refuses to load it.

The refusal reads as the failure a truthful import would raise: a
``ModuleNotFoundError`` naming the package not installed the module needs.

Private to the scan.
"""

from __future__ import annotations

import copy
import importlib.abc
import sys
import threading
from typing import TYPE_CHECKING, final, override

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Sequence
    from importlib.machinery import ModuleSpec
    from types import ModuleType

__all__ = ["RefusalFinder", "SetAsideRefused", "holder_of"]


@final
class SetAsideRefused(ModuleNotFoundError):  # noqa: N818 — named for what the scan did, as its report is
    """Raised by an import of a set-aside module, or of one lying under a set-aside package.

    It reads as the failure of a truthful import of the module: it names, and
    says, the package not installed that the module needs — not the module
    itself, which ``from package import module`` would take for "no such
    module", and go on.

    Attributes:
        module: The module refused.
        through: The set-aside module the name is, or lies under.
    """

    def __init__(self, module: str, through: str, lacking: str) -> None:
        """Refuse ``module``, set aside as, or under, ``through``, for ``lacking`` not installed."""
        super().__init__(f"No module named {lacking!r}", name=lacking)
        self.module = module
        self.through = through


def holder_of(module: str, packages: Collection[str]) -> str | None:
    """Return the one of ``packages`` that ``module`` is, or lies in; ``None`` if none.

    The nearest, should several hold it: ``module`` itself, else its innermost
    package among them. Asked for ``module`` and each of its packages in
    turn, not for each of ``packages``.
    """
    candidate = module
    while candidate:
        if candidate in packages:
            return candidate
        candidate = candidate.rpartition(".")[0]
    return None


@final
class _RefusingLoader(importlib.abc.Loader):
    """Loads nothing: the module it was found for is set aside."""

    def __init__(self, through: str, lacking: Callable[[str], str]) -> None:
        self._through = through
        self._lacking = lacking

    @override
    def create_module(self, spec: ModuleSpec) -> ModuleType | None:
        # Raised before the import system puts anything in sys.modules.
        raise SetAsideRefused(spec.name, self._through, self._lacking(self._through))

    @override
    def exec_module(self, module: ModuleType) -> None:
        raise SetAsideRefused(module.__name__, self._through, self._lacking(self._through))


@final
class RefusalFinder(importlib.abc.MetaPathFinder):
    """Refuses every set-aside module, on the thread that created it.

    Placed first on ``sys.meta_path`` for the scan's length. It reads the
    names set aside from the collection it was given, as that grows.
    """

    def __init__(self, set_aside: Collection[str], lacking: Callable[[str], str]) -> None:
        """Refuse each name of ``set_aside``, and every name under one.

        ``lacking`` gives, for a set-aside module, the package not installed
        a truthful import of it would fail for.
        """
        self._set_aside = set_aside
        self._lacking = lacking
        self._thread = threading.get_ident()

    @override
    def find_spec(
        self,
        fullname: str,
        path: Sequence[str] | None,
        target: ModuleType | None = None,
    ) -> ModuleSpec | None:
        """Answer for a set-aside name with a record refusing to load; else ``None``."""
        if threading.get_ident() != self._thread:
            return None
        through = holder_of(fullname, self._set_aside)
        if through is None:
            return None
        for finder in sys.meta_path:
            if finder is self:
                continue
            found = finder.find_spec(fullname, path, target)
            if found is not None:
                # A copy: the finder that found it may hand out the same record again.
                refused = copy.copy(found)
                refused.loader = _RefusingLoader(through, self._lacking)
                return refused
        return None

    def install(self) -> None:
        """Go first of all finders."""
        sys.meta_path.insert(0, self)

    def remove(self) -> None:
        """Leave ``sys.meta_path``, if still there."""
        if self in sys.meta_path:
            sys.meta_path.remove(self)
