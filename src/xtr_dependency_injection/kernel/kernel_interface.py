"""What a service may know about the kernel that built it."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Protocol, final, runtime_checkable

from xtr_dependency_injection.diagnostics import KernelReport

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["KernelInterface"]


@runtime_checkable
class KernelInterface(Protocol):
    """The kernel, as a service: its identity, environment and what it decided."""

    @property
    def name(self) -> str:
        """The application's name."""
        ...

    @property
    def environment(self) -> str:
        """The environment this container was built for."""
        ...

    @property
    def debug(self) -> bool:
        """Whether the kernel runs in debug mode."""
        ...

    @property
    def project_dir(self) -> Path:
        """The directory of the nearest ``pyproject.toml`` above the application."""
        ...

    @property
    def bundles(self) -> tuple[str, ...]:
        """Active bundle names, in dependency order, ``"kernel"`` first."""
        ...

    @property
    def report(self) -> KernelReport:
        """What the build decided; available once compiled, before boot."""
        ...


@final
class _KernelInfo:
    """The one ``KernelInterface`` the kernel provides, filled in as the build proceeds."""

    __slots__ = ("_bundles", "_debug", "_environment", "_name", "_project_dir", "_report")

    def __init__(self) -> None:
        """Start blank; the kernel fills each field in the step that decides it."""
        self._name = ""
        self._environment = ""
        self._debug = False
        self._project_dir = Path()
        self._bundles: tuple[str, ...] = ()
        self._report = KernelReport()

    def identify(self, *, name: str, environment: str, debug: bool, project_dir: Path) -> None:
        """Record who the kernel is and what it is built for."""
        self._name = name
        self._environment = environment
        self._debug = debug
        self._project_dir = project_dir

    def activate(self, bundles: Sequence[str]) -> None:
        """Record the active bundles."""
        self._bundles = tuple(bundles)

    def attach(self, report: KernelReport) -> None:
        """Record the final report."""
        self._report = report

    @property
    def name(self) -> str:
        """The application's name."""
        return self._name

    @property
    def environment(self) -> str:
        """The environment this container was built for."""
        return self._environment

    @property
    def debug(self) -> bool:
        """Whether the kernel runs in debug mode."""
        return self._debug

    @property
    def project_dir(self) -> Path:
        """The directory of the nearest ``pyproject.toml`` above the application."""
        return self._project_dir

    @property
    def bundles(self) -> tuple[str, ...]:
        """Active bundle names, in dependency order, ``"kernel"`` first."""
        return self._bundles

    @property
    def report(self) -> KernelReport:
        """What the build decided."""
        return self._report
