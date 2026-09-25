from __future__ import annotations

from typing_extensions import override

from tests.support.bundles import Echo
from xtr_dependency_injection.builder.container_builder import ContainerBuilder
from xtr_dependency_injection.decorator.as_decorator import Inner, as_decorator
from xtr_dependency_injection.decorator.compiler_pass import compiler_pass


class Marker:
    def __init__(self, text: str) -> None:
        self.text: str = text


@compiler_pass
def add_marker(builder: ContainerBuilder) -> None:
    builder.instance(Marker(f"echo defined: {builder.has(Echo)}"))


@as_decorator(Echo)
class PoliteEcho(Echo):
    def __init__(self, inner: Inner[Echo]) -> None:
        super().__init__(inner.config)
        self.inner: Echo = inner

    @override
    def say(self) -> str:
        return f"please, {self.inner.say()}"
