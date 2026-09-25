from __future__ import annotations

from typing import Annotated

from wireup import Inject, injectable

from tests.support.bundles import Echo, Plugin
from xtr_dependency_injection.decorator.when import when


@injectable
class Greeter:
    def __init__(
        self, echo: Echo, punctuation: Annotated[str, Inject(config="app.punctuation")]
    ) -> None:
        self.echo: Echo = echo
        self.punctuation: str = punctuation

    def greet(self) -> str:
        return self.echo.say() + self.punctuation


class TaggedPlugin(Plugin):
    __echo_tags__: tuple[str, ...] = ("alpha", "beta")


@when("dev")
@injectable
class DevOnly:
    pass
