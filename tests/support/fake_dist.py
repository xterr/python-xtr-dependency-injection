"""Installing throwaway distributions, with entry points, for one test.

Discovery reads real ``importlib.metadata`` entry points, so the only honest
way to test it is to install something: a ``*.dist-info`` directory with an
``entry_points.txt``, plus the modules it points at, on ``sys.path``.
"""

from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

GROUP = "xtr_dependency_injection.bundles"


@dataclass
class FakeDistributions:
    root: Path
    installed: list[str] = field(default_factory=list)

    def install(
        self,
        distribution: str,
        entry_points: Mapping[str, str],
        modules: Mapping[str, str] | None = None,
    ) -> None:
        # Installers write the normalized name: importlib.metadata reads a
        # distribution's name from this directory, up to the first "-".
        info = self.root / f"{distribution.replace('-', '_')}-0.0.0.dist-info"
        info.mkdir()
        _ = (info / "METADATA").write_text(
            f"Metadata-Version: 2.1\nName: {distribution}\nVersion: 0.0.0\n"
        )
        lines = [f"[{GROUP}]", *(f"{name} = {value}" for name, value in entry_points.items())]
        _ = (info / "entry_points.txt").write_text("\n".join(lines) + "\n")
        for module, source in (modules or {}).items():
            self._write_module(module, source)
        self.installed.append(distribution)
        importlib.invalidate_caches()

    def add_modules(self, modules: Mapping[str, str]) -> None:
        for module, source in modules.items():
            self._write_module(module, source)
        importlib.invalidate_caches()

    def _write_module(self, module: str, source: str) -> None:
        *packages, leaf = module.split(".")
        directory = self.root
        for package in packages:
            directory /= package
            directory.mkdir(exist_ok=True)
            init = directory / "__init__.py"
            if not init.exists():
                _ = init.write_text("")
        _ = (directory / f"{leaf}.py").write_text(source)


@pytest.fixture
def fake_dist(tmp_path: Path) -> Iterator[FakeDistributions]:
    root = tmp_path / "site"
    root.mkdir()
    sys.path.insert(0, str(root))
    importlib.invalidate_caches()
    try:
        yield FakeDistributions(root)
    finally:
        sys.path.remove(str(root))
        for name, module in list(sys.modules.items()):
            origin = getattr(module, "__file__", None)
            if isinstance(origin, str) and origin.startswith(str(root)):
                del sys.modules[name]
        importlib.invalidate_caches()
