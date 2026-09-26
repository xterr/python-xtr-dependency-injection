from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from xtr_dependency_injection.config.configure import configure
from xtr_dependency_injection.config.parameters import parameters
from xtr_dependency_injection.decorator.as_decorator import AutowireDecorated, as_decorator
from xtr_dependency_injection.decorator.compiler_pass import compiler_pass
from xtr_dependency_injection.decorator.lifecycle import on_boot, on_shutdown

if TYPE_CHECKING:
    from xtr_dependency_injection.builder.container_builder import ContainerBuilder


class Target:
    pass


@configure
def configured() -> int:
    return 1


@parameters
def provided() -> dict[str, object]:
    return {}


@compiler_pass
class Adjusted:
    def process(self, builder: ContainerBuilder) -> None:
        del builder


@on_boot
def booted() -> None:
    pass


@on_shutdown
def stopped() -> None:
    pass


@as_decorator(Target)
class Wrapping:
    def __init__(self, inner: Annotated[Target, AutowireDecorated()]) -> None:
        self.inner: Target = inner
