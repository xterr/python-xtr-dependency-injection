"""The package behaves the same when the web framework is not importable.

The dev group installs the web framework, so every other test in this suite
runs with it there — and the engine's injection markers take a different shape
when it is (see ``tests/unit/decorator/test_autowire.py``). A fresh interpreter
that cannot import it is the only way to keep the other path covered; nothing
in the installed environment can express "absent".
"""

from __future__ import annotations

import subprocess
import sys

SCRIPT = """
import importlib
import sys

sys.modules["fastapi"] = None

try:
    importlib.import_module("fastapi")
except ModuleNotFoundError:
    pass
else:
    raise AssertionError("a blanked module stayed importable: this run proves nothing")

from xtr_service_contracts import ContainerInterface

from xtr_dependency_injection import Autowire, Injected, Kernel

roots = {cls.__module__.partition(".")[0] for cls in Autowire.__mro__}
assert not roots & {"fastapi", "starlette"}, roots


def main(container: Injected[ContainerInterface]) -> int:
    return 0 if container.has(ContainerInterface) else 1


kernel = Kernel("xtr_dependency_injection", env="test", bundles={}, resources=())
raise SystemExit(kernel.run(main))
"""


def test_the_markers_and_a_boot_hold_without_the_web_framework() -> None:
    completed = subprocess.run(
        [sys.executable, "-c", SCRIPT],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout
