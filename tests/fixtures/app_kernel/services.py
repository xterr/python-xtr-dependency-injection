from __future__ import annotations

from typing import Annotated

from tests.support.bundles import Echo, Plugin
from xtr_dependency_injection.decorator.as_service import as_service
from xtr_dependency_injection.decorator.autowire import Autowire
from xtr_dependency_injection.decorator.when import when


@as_service()
class Greeter:
    def __init__(
        self, echo: Echo, punctuation: Annotated[str, Autowire(param="app.punctuation")]
    ) -> None:
        self.echo: Echo = echo
        self.punctuation: str = punctuation

    def greet(self) -> str:
        return self.echo.say() + self.punctuation


class TaggedPlugin(Plugin):
    __echo_tags__: tuple[str, ...] = ("alpha", "beta")


@when("dev")
@as_service()
class DevOnly:
    pass
