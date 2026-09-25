from __future__ import annotations

from xtr_dependency_injection.decorator.when import when, when_not


@when("dev")
def dev_only() -> None:
    pass


@when_not("dev")
class NotInDev:
    pass
