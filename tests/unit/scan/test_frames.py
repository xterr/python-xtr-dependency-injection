from __future__ import annotations

import importlib
import threading
from typing import TYPE_CHECKING, cast

from xtr_dependency_injection.scan._frames import running_module

if TYPE_CHECKING:
    from tests.support.modules import ScratchModules


def test_it_names_the_module_whose_body_runs(scratch_modules: ScratchModules) -> None:
    scratch_modules.write(
        {
            "acme_app.asking": (
                "from xtr_dependency_injection.scan._frames import running_module\n\n"
                "def ask():\n    return running_module()\n\n"
                "ASKED = ask()\n"
            )
        }
    )

    module = importlib.import_module("acme_app.asking")

    assert cast("str", module.ASKED) == "acme_app.asking"


def test_outside_any_module_body_it_names_none() -> None:
    found: list[str | None] = []
    thread = threading.Thread(target=lambda: found.append(running_module()))

    thread.start()
    thread.join()

    assert found == [None]
