"""Writing throwaway Python modules on ``sys.path`` for one test.

Replaces the previous entry-point-based ``fake_dist`` fixture: bundles are
now listed by the application (a ``bundles.py`` mapping or the kernel's
``bundles=`` argument), so a test only needs the modules to be importable —
no distribution metadata, no entry points.
"""

from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping


@dataclass
class ScratchModules:
    root: Path

    def write(self, modules: Mapping[str, str]) -> None:
        """Write each ``module`` (dotted name) with the given source text."""
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
def scratch_modules(tmp_path: Path) -> Iterator[ScratchModules]:
    root = tmp_path / "site"
    root.mkdir()
    sys.path.insert(0, str(root))
    importlib.invalidate_caches()
    try:
        yield ScratchModules(root)
    finally:
        sys.path.remove(str(root))
        for name, module in list(sys.modules.items()):
            origin = getattr(module, "__file__", None)
            if isinstance(origin, str) and origin.startswith(str(root)):
                del sys.modules[name]
        importlib.invalidate_caches()
