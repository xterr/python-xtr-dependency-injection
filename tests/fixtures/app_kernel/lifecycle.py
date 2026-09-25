from __future__ import annotations

from wireup import Injected

from tests.fixtures.app_kernel.services import Greeter
from tests.support.bundles import EVENTS
from xtr_dependency_injection.decorator.lifecycle import on_boot, on_shutdown


@on_boot
async def greet_on_boot(greeter: Injected[Greeter]) -> None:
    EVENTS.append(f"boot:app {greeter.greet()}")


@on_boot(priority=10)
def first_on_boot() -> None:
    EVENTS.append("boot:app first")


@on_shutdown
def goodbye() -> None:
    EVENTS.append("shutdown:app")
